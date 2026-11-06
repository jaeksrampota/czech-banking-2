"""HTTP client for the logged-in FINeCIM site (https://www.finecim.cz).

Single-threaded and polite: every request is spaced by ``rate_limit_seconds``, transport
errors and 5xx answers are retried with exponential backoff, HTTP 429 (and 503) honour a
``Retry-After`` header (capped at ``MAX_RETRY_AFTER_SECONDS``), and a session that expires
mid-run triggers exactly one automatic re-login. Forbidden URLs (sign-out, favorites,
read-later, PDF export, the AI assistant, early warnings) are refused before sending,
on every redirect hop, and on the final URL. Cookies persist to a JSON file so a later
run can reuse the session. Credentials and cookie values are never logged.
"""

from __future__ import annotations

import contextlib
import http.cookiejar
import json
import logging
import math
import os
import re
import tempfile
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

from src.finecim.credentials import Credentials, load_credentials

__all__ = [
    "BASE_URL",
    "DEFAULT_USER_AGENT",
    "MAX_RETRY_AFTER_SECONDS",
    "SIGN_IN_PATH",
    "SIGN_OUT_MARKER",
    "FinecimAuthError",
    "FinecimClient",
    "FinecimForbiddenURLError",
    "FinecimHTTPError",
    "is_forbidden_url",
    "parse_login_form",
    "parse_nette_snippets",
    "parse_retry_after",
]

logger = logging.getLogger(__name__)

BASE_URL = "https://www.finecim.cz"
SIGN_IN_PATH = "/cz/sign/in"
SIGN_OUT_MARKER = 'href="/cz/sign/out"'
LOGIN_FORM_MARKER = 'id="kt_login_form"'

# Same string as src.collectors.base.USER_AGENTS[0] (not imported: that module pulls in
# the database and alerting stack).
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Nette signals (?do=...) and paths the scraper must never request (spec section 7).
_FORBIDDEN_SIGNALS = ("favorite", "readlater", "exporttopdf", "askferda")
_FORBIDDEN_PATH_RE = re.compile(r"(^|/)(sign/+out|early[-_]?warnings?)(/|\.|$)", re.IGNORECASE)

_RETRY_STATUSES = range(500, 600)
#: Statuses whose Retry-After header is honoured (otherwise exponential backoff).
_RETRY_AFTER_STATUSES = (429, 503)
#: Upper bound for a server-requested Retry-After wait.
MAX_RETRY_AFTER_SECONDS = 120.0

#: Headers Nette's AJAX layer (naja / nette.ajax.js) sends for a snippet request.
_AJAX_HEADERS = {
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, text/html, */*; q=0.01",
}


class FinecimAuthError(RuntimeError):
    """Login failed, or the session could not be (re-)established."""


class FinecimHTTPError(RuntimeError):
    """A request failed for good (4xx, or 5xx / transport error after all retries)."""

    def __init__(self, message: str, *, status_code: int | None, url: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.url = url


class FinecimForbiddenURLError(ValueError):
    """The URL is on the never-request list (favorites, read-later, PDF export, sign-out, ...)."""


def _is_forbidden_signal(value: str) -> bool:
    value = value.lower()
    return any(sig in value for sig in _FORBIDDEN_SIGNALS)


def is_forbidden_url(url: str) -> bool:
    """True for URLs the scraper must never request (spec section 7)."""
    parts = urlsplit(str(url))
    if _FORBIDDEN_PATH_RE.search(unquote(parts.path)):
        return True
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() in ("do", "_do") and _is_forbidden_signal(value):
            return True
    return False


def _param_items(params: Any) -> list[tuple[str, Any]]:
    """Flatten any params shape httpx accepts (mapping, list of pairs, query string,
    httpx.QueryParams) into (key, value) pairs; list/tuple values become one pair each."""
    if params is None:
        return []
    if isinstance(params, bytes):
        params = params.decode("utf-8", "replace")
    if isinstance(params, str):
        return parse_qsl(params.lstrip("?"), keep_blank_values=True)
    if isinstance(params, httpx.QueryParams):
        return list(params.multi_items())
    pairs = params.items() if isinstance(params, Mapping) else params
    items: list[tuple[str, Any]] = []
    for key, raw in pairs:
        values = raw if isinstance(raw, list | tuple) else [raw]
        items.extend((str(key), value) for value in values)
    return items


def _forbidden_params(params: Any, *, signals_only: bool = False) -> bool:
    """True when request params would turn a request into a forbidden one: a ``do`` /
    ``_do`` value naming a forbidden signal, or (unless ``signals_only``) any value that
    is (or embeds) a forbidden path or ``do=`` signal. Accepts a mapping, a list of
    pairs, a query string or httpx.QueryParams. ``signals_only`` is used for POST bodies,
    whose free-text values (e.g. a password) must not be pattern-matched."""
    for key, value in _param_items(params):
        if value is None:
            continue
        text = str(value)
        if str(key).lower() in ("do", "_do") and _is_forbidden_signal(text):
            return True
        if signals_only:
            continue
        if _FORBIDDEN_PATH_RE.search(unquote(text)):
            return True
        if "do=" in text.lower() and is_forbidden_url(text if "?" in text else "?" + text):
            return True
    return False


def parse_retry_after(value: str | None, *, now: datetime | None = None) -> float | None:
    """Seconds to wait from a ``Retry-After`` header (delta-seconds or an HTTP-date).
    Returns None when absent or unparseable; never negative; not capped here."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        pass
    else:
        return max(0.0, seconds) if math.isfinite(seconds) else None
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    now = now or datetime.now(UTC)
    return max(0.0, (when - now).total_seconds())


def _json_object(text: str) -> dict | None:
    stripped = (text or "").lstrip("\ufeff \t\r\n")
    if not stripped.startswith("{"):
        return None
    try:
        payload = json.loads(stripped)
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def parse_nette_snippets(text: str) -> str | None:
    """If ``text`` is a Nette AJAX JSON payload with a ``snippets`` object, return the
    snippet HTML concatenated in payload order; otherwise None."""
    payload = _json_object(text)
    if payload is None or not isinstance(payload.get("snippets"), dict):
        return None
    return "\n".join(v for v in payload["snippets"].values() if isinstance(v, str))


def _nette_redirect(text: str) -> str | None:
    """The ``redirect`` target of a Nette AJAX JSON payload, if any."""
    payload = _json_object(text)
    if payload is not None and isinstance(payload.get("redirect"), str):
        return payload["redirect"]
    return None


def parse_login_form(html: str) -> dict:
    """Parse the Nette sign-in form.

    Returns ``{"action": <raw action attribute, may be relative>, "fields": {hidden inputs}}``
    (the hidden inputs are ``_token_`` and ``_do``). Raises FinecimAuthError when the page
    has no sign-in form."""
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form", id="kt_login_form")
    if form is None:
        form = next(
            (f for f in soup.find_all("form") if f.find("input", attrs={"name": "passwd"})),
            None,
        )
    if form is None:
        raise FinecimAuthError("FINeCIM sign-in form not found on the page")
    fields: dict[str, str] = {}
    for inp in form.find_all("input"):
        name = inp.get("name")
        if name and (inp.get("type") or "").lower() == "hidden":
            fields[name] = inp.get("value") or ""
    return {"action": form.get("action") or "", "fields": fields}


class FinecimClient:
    """Rate-limited, session-aware GET client for FINeCIM.

    ``max_retries``, ``sleep`` and ``clock`` are extra keyword arguments (beyond the
    design spec) so tests can run without real waiting."""

    def __init__(
        self,
        credentials: Credentials | None = None,
        *,
        cookie_path: str | os.PathLike | None = "data/finecim_cookies.json",
        rate_limit_seconds: float = 1.5,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        user_agent: str | None = None,
        max_retries: int = 3,
        sleep: Callable[[float], Any] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._credentials = credentials
        self.cookie_path = Path(cookie_path) if cookie_path is not None else None
        self.rate_limit_seconds = max(0.0, float(rate_limit_seconds))
        self.timeout = timeout
        self._transport = transport
        self.user_agent = user_agent or DEFAULT_USER_AGENT
        self.max_retries = max(0, int(max_retries))
        self._sleep = sleep
        self._clock = clock
        self._last_request_at: float | None = None
        self._client: httpx.Client | None = None
        self.request_count = 0
        self.login_count = 0

    # -- lifecycle ---------------------------------------------------------------------

    def __enter__(self) -> FinecimClient:
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def open(self) -> None:
        """Open the underlying httpx.Client (idempotent) and load persisted cookies."""
        if self._client is not None:
            return
        self._client = httpx.Client(
            follow_redirects=True,
            timeout=self.timeout,
            transport=self._transport,
            event_hooks={"request": [self._guard_request]},
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "cs,en;q=0.5",
            },
        )
        self.load_cookies()

    def close(self) -> None:
        """Save cookies and close the underlying client (idempotent)."""
        if self._client is None:
            return
        try:
            self.save_cookies()
        finally:
            self._client.close()
            self._client = None

    @property
    def http(self) -> httpx.Client:
        if self._client is None:
            self.open()
        assert self._client is not None
        return self._client

    @property
    def credentials(self) -> Credentials:
        """The credentials, resolved lazily with load_credentials() when none were given."""
        if self._credentials is None:
            self._credentials = load_credentials()
        return self._credentials

    # -- cookies -----------------------------------------------------------------------

    def load_cookies(self) -> int:
        """Load cookies from ``cookie_path`` into the session. Returns how many were loaded.
        A missing or corrupt file is not an error (the session simply starts empty)."""
        if self.cookie_path is None or self._client is None or not self.cookie_path.is_file():
            return 0
        try:
            data = json.loads(self.cookie_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("FINeCIM cookie file %s is unreadable; starting a fresh session", self.cookie_path)
            return 0
        if not isinstance(data, list):
            return 0
        now = time.time()
        loaded = 0
        jar = self._client.cookies.jar
        for item in data:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            expires = item.get("expires")
            if expires is not None:
                try:
                    expires = int(expires)
                except (TypeError, ValueError):
                    expires = None
            if expires is not None and expires <= now:
                continue
            domain = str(item.get("domain") or "")
            jar.set_cookie(
                http.cookiejar.Cookie(
                    version=0,
                    name=str(item["name"]),
                    value=str(item.get("value") or ""),
                    port=None,
                    port_specified=False,
                    domain=domain,
                    domain_specified=bool(domain),
                    domain_initial_dot=domain.startswith("."),
                    path=str(item.get("path") or "/"),
                    path_specified=True,
                    secure=False,
                    expires=expires,
                    discard=expires is None,
                    comment=None,
                    comment_url=None,
                    rest={},
                )
            )
            loaded += 1
        return loaded

    def save_cookies(self) -> None:
        """Write the session cookies as a JSON list of {name, value, domain, path, expires}
        (mode 0600 where the OS supports it; the directory is created)."""
        if self.cookie_path is None or self._client is None:
            return
        rows = [
            {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path, "expires": c.expires}
            for c in self._client.cookies.jar
        ]
        path = self.cookie_path
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".finecim_cookies.", dir=str(path.parent))
        try:
            with contextlib.suppress(OSError):
                os.chmod(tmp, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(rows, fh, ensure_ascii=False, indent=1)
            os.replace(tmp, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
        with contextlib.suppress(OSError):
            os.chmod(path, 0o600)

    # -- helpers -----------------------------------------------------------------------

    @staticmethod
    def absolute(url: str) -> str:
        """Join ``url`` against BASE_URL; absolute URLs are returned unchanged."""
        return urljoin(BASE_URL + "/", url)

    @staticmethod
    def looks_like_login_page(final_url: str, html: str) -> bool:
        """Login-detection rule: the final URL contains /cz/sign/in or the body contains
        id="kt_login_form"."""
        return SIGN_IN_PATH in (final_url or "") or LOGIN_FORM_MARKER in (html or "")

    def _throttle(self) -> None:
        if self._last_request_at is not None and self.rate_limit_seconds > 0:
            wait = self._last_request_at + self.rate_limit_seconds - self._clock()
            if wait > 0:
                self._sleep(wait)
        self._last_request_at = self._clock()

    def _backoff(self, attempt: int) -> None:
        self._sleep(max(self.rate_limit_seconds, 1.0) * (2 ** attempt))

    @staticmethod
    def _guard_request(request: httpx.Request) -> None:
        """httpx request hook: runs before every hop, redirects included, so a redirect
        towards a forbidden URL is never sent."""
        if is_forbidden_url(str(request.url)):
            raise FinecimForbiddenURLError(
                f"refusing to request a forbidden FINeCIM URL: {request.url}"
            )

    @staticmethod
    def _check_final_url(response: httpx.Response) -> None:
        """Refuse (and discard) a response whose redirect chain landed on a forbidden URL."""
        for hop in (*response.history, response):
            if is_forbidden_url(str(hop.url)):
                response.close()
                raise FinecimForbiddenURLError(
                    f"a FINeCIM redirect landed on a forbidden URL: {hop.url}"
                )

    def _request(self, method: str, url: str, *, params: dict | None = None,
                 data: dict | None = None, headers: dict | None = None) -> httpx.Response:
        """One logical request: forbidden-URL guard (URL, params, every redirect hop and
        the final URL), rate limit, retries on transport errors and 5xx with exponential
        backoff; 429 / 503 honour Retry-After (capped at MAX_RETRY_AFTER_SECONDS)."""
        if (is_forbidden_url(url) or _forbidden_params(params)
                or _forbidden_params(data, signals_only=True)):
            raise FinecimForbiddenURLError(f"refusing to request a forbidden FINeCIM URL: {url}")
        attempt = 0
        while True:
            self._throttle()
            self.request_count += 1
            wait: float | None = None
            try:
                response = self.http.request(method, url, params=params, data=data, headers=headers)
            except httpx.TransportError as exc:
                if attempt >= self.max_retries:
                    raise FinecimHTTPError(
                        f"{method} {url} failed after {attempt + 1} attempts: {type(exc).__name__}",
                        status_code=None, url=url,
                    ) from exc
                logger.info("FINeCIM %s %s: %s, retrying", method, url, type(exc).__name__)
            else:
                self._check_final_url(response)
                status = response.status_code
                if status not in _RETRY_STATUSES and status != 429:
                    return response
                if attempt >= self.max_retries:
                    raise FinecimHTTPError(
                        f"{method} {url} answered HTTP {status} after {attempt + 1} attempts",
                        status_code=status, url=str(response.url),
                    )
                if status in _RETRY_AFTER_STATUSES:
                    wait = parse_retry_after(response.headers.get("Retry-After"))
                    if wait is not None:
                        wait = min(wait, MAX_RETRY_AFTER_SECONDS)
                logger.info("FINeCIM %s %s: HTTP %s, retrying", method, url, status)
                response.close()
            if wait is not None:
                self._sleep(wait)
            else:
                self._backoff(attempt)
            attempt += 1

    @classmethod
    def _is_signed_in(cls, response: httpx.Response) -> bool:
        text = response.text
        return not cls.looks_like_login_page(str(response.url), text) and SIGN_OUT_MARKER in text

    # -- public API --------------------------------------------------------------------

    def _sign_in_url(self, signin_url: str | None) -> str:
        """The sign-in URL to GET: ``signin_url`` (e.g. the live
        ``/cz/sign/in?backlink=...`` a content page redirected to) when it is a FINeCIM
        sign-in URL, otherwise the bare SIGN_IN_PATH."""
        if signin_url:
            url = self.absolute(signin_url)
            if self._is_finecim_sign_in_url(url):
                return url
        return self.absolute(SIGN_IN_PATH)

    @staticmethod
    def _is_finecim_host(url: str) -> bool:
        """True when ``url`` is https on the FINeCIM host itself (credentials go nowhere else)."""
        parts = urlsplit(url)
        base = urlsplit(BASE_URL)
        return parts.scheme == base.scheme and parts.netloc == base.netloc

    @classmethod
    def _is_finecim_sign_in_url(cls, url: str) -> bool:
        return (cls._is_finecim_host(url)
                and urlsplit(url).path.rstrip("/") == SIGN_IN_PATH
                and not is_forbidden_url(url))

    @staticmethod
    def _has_login_form(response: httpx.Response) -> bool:
        if response.status_code >= 400:
            return False
        try:
            parse_login_form(response.text)
        except FinecimAuthError:
            return False
        return True

    def login(self, signin_url: str | None = None, *, page: httpx.Response | None = None) -> None:
        """GET the sign-in page, parse _token_/_do/action, POST the form.

        ``signin_url`` (optional) is the sign-in URL to use instead of the bare
        ``/cz/sign/in``, typically the ``/cz/sign/in?backlink=...`` a content page was
        redirected to, so the POST keeps that backlink. ``page`` (optional) is an
        already fetched response carrying the sign-in form; it is reused instead of a
        second GET. Raises FinecimAuthError on failure (the message never contains
        credentials)."""
        # Only a sign-in page served by FINeCIM itself may be reused: a redirect or a
        # scraped page on another host must never receive the credentials.
        if (page is None or not self._is_finecim_sign_in_url(str(page.url))
                or not self._has_login_form(page)):
            page = self._request("GET", self._sign_in_url(signin_url))
        if page.status_code >= 400:
            raise FinecimAuthError(f"FINeCIM sign-in page answered HTTP {page.status_code}")
        if self._is_signed_in(page):
            logger.info("FINeCIM session already valid")
            return
        form = parse_login_form(page.text)
        action = self._login_action(str(page.url), form["action"])
        if not self._is_finecim_host(action) or is_forbidden_url(action):
            raise FinecimAuthError(
                f"refusing to post credentials outside {BASE_URL}: sign-in form action is off-host"
            )
        creds = self.credentials
        data = dict(form["fields"])
        data.update({
            "username": creds.username,
            "passwd": creds.password,
            "remember": "on",
            "login": "Přihlásit",
        })
        self.login_count += 1
        logger.info("Logging in to FINeCIM (credentials from %s)", creds.source)
        response = self._request("POST", action, data=data)
        if response.status_code >= 400:
            raise FinecimAuthError(f"FINeCIM login answered HTTP {response.status_code}")
        if not self._is_signed_in(response):
            raise FinecimAuthError(
                "FINeCIM login failed: the sign-in page was served again (wrong username or password?)"
            )
        self.save_cookies()

    @staticmethod
    def _login_action(page_url: str, raw_action: str) -> str:
        """Resolve the sign-in form action against the sign-in page's final URL. When the
        action carries no query string, the live ``backlink`` from the page URL is kept
        (Nette posts the form to ``/cz/sign/in?backlink=...``)."""
        if not raw_action:
            return page_url
        action = urljoin(page_url, raw_action)
        parts = urlsplit(action)
        if parts.query:
            return action
        backlinks = [(k, v) for k, v in parse_qsl(urlsplit(page_url).query, keep_blank_values=True)
                     if k == "backlink"]
        if not backlinks:
            return action
        return urlunsplit(parts._replace(query=urlencode(backlinks)))

    def is_logged_in(self) -> bool:
        """Cheap GET /cz/ and apply the login-detection rule (no automatic login)."""
        response = self._request("GET", self.absolute("/cz/"))
        if self.looks_like_login_page(str(response.url), response.text):
            return False
        if response.status_code >= 400:
            raise FinecimHTTPError(f"GET /cz/ answered HTTP {response.status_code}",
                                   status_code=response.status_code, url=str(response.url))
        return True

    def get(self, path_or_url: str, *, params: dict | None = None) -> str:
        """Rate-limited GET returning response text. Resolves relative paths against BASE_URL.
        If the login-detection rule fires, calls login() once and retries; a second failure
        raises FinecimAuthError. Retries transport errors / 5xx up to ``max_retries`` (3)
        times with backoff (429 / 503 honour Retry-After). 4xx (other than the login
        redirect) raise FinecimHTTPError. Errors from login() (FinecimAuthError,
        CredentialsError) propagate unchanged."""
        return self._get_text(path_or_url, params=params)

    def _get_text(self, path_or_url: str, *, params: dict | None = None,
                  headers: dict | None = None, ajax: bool = False) -> str:
        url = self.absolute(path_or_url)
        relogged = False
        while True:
            response = self._request("GET", url, params=params, headers=headers)
            text = response.text
            needs_login = self.looks_like_login_page(str(response.url), text)
            signin_url: str | None = str(response.url)
            if ajax and not needs_login:
                redirect = _nette_redirect(text)
                needs_login = redirect is not None and SIGN_IN_PATH in redirect
                signin_url = redirect
            if needs_login:
                if relogged:
                    raise FinecimAuthError(f"still redirected to the sign-in page after login: {url}")
                logger.info("FINeCIM session expired or missing; logging in")
                # Reuse the sign-in page we were redirected to (it carries the live
                # ?backlink= that the POST must keep); login() falls back to a fresh GET
                # of that URL when the response has no usable form.
                self.login(signin_url, page=response)
                relogged = True
                continue
            if response.status_code >= 400:
                raise FinecimHTTPError(f"GET {url} answered HTTP {response.status_code}",
                                       status_code=response.status_code, url=str(response.url))
            if ajax:
                snippets = parse_nette_snippets(text)
                if snippets is not None:
                    return snippets
                if _json_object(text) is not None:
                    # A Nette JSON payload without snippets (e.g. {"state": []} or a
                    # redirect elsewhere) carries no fragment HTML.
                    return ""
            return text

    def get_fragment(self, url: str) -> str:
        """GET an AJAX fragment (campaign creatives) the way Nette's JS does, with
        ``X-Requested-With: XMLHttpRequest``. A JSON payload with a ``snippets`` object
        yields the concatenated snippet HTML; an HTML answer is returned as is. A JSON
        ``redirect`` to the sign-in page triggers the one automatic re-login; any other JSON
        payload without snippets yields ""."""
        return self._get_text(url, headers=dict(_AJAX_HEADERS), ajax=True)
