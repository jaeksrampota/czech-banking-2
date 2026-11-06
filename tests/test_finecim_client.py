"""Tests for src.finecim.client against an httpx.MockTransport emulation of FINeCIM."""

import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
import src.finecim.client as client_mod
from src.finecim.client import (
    BASE_URL,
    MAX_RETRY_AFTER_SECONDS,
    FinecimAuthError,
    FinecimClient,
    FinecimForbiddenURLError,
    FinecimHTTPError,
    is_forbidden_url,
    parse_login_form,
    parse_nette_snippets,
    parse_retry_after,
)
from src.finecim.credentials import Credentials, CredentialsError

FIXTURES = Path(__file__).parent / "fixtures" / "finecim"
SIGNIN_HTML = (FIXTURES / "signin.html").read_text(encoding="utf-8")
HOME_HTML = '<html><body><a href="/cz/sign/out">Odhlásit</a><div id="kt_content">home</div></body></html>'
CREDS = Credentials("tester@example.cz", "right-password", "test")


class FakeSite:
    """Minimal FINeCIM: session cookie gate, Nette sign-in form, a content page."""

    def __init__(self):
        self.sessions: set[str] = set()
        self.logins = 0
        self.posts: list[dict] = []
        self.requests: list[httpx.Request] = []
        self.counter = 0
        self.overrides: dict[str, list] = {}  # path -> queued responses / exceptions

    def expire_sessions(self):
        self.sessions.clear()

    def _authed(self, request: httpx.Request) -> bool:
        cookie = request.headers.get("cookie", "")
        for part in cookie.split(";"):
            name, _, value = part.strip().partition("=")
            if name == "PHPSESSID" and value in self.sessions:
                return True
        return False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        queue = self.overrides.get(path)
        if queue:
            item = queue.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        if path == "/cz/sign/in":
            if request.method == "POST":
                form = {k: v[0] for k, v in parse_qs(request.content.decode("utf-8")).items()}
                self.posts.append(form)
                ok = (
                    form.get("username") == CREDS.username
                    and form.get("passwd") == CREDS.password
                    and form.get("_token_") == "aqzz8mcz2zKlgU5SF/xBXNMmotkIetPqTzVlQ="
                    and form.get("_do") == "signIn-signInForm-submit"
                    and form.get("remember") == "on"
                    and form.get("login") == "Přihlásit"
                )
                if not ok:
                    return httpx.Response(200, html=SIGNIN_HTML)
                self.logins += 1
                self.counter += 1
                sid = f"sess{self.counter}"
                self.sessions.add(sid)
                return httpx.Response(
                    302,
                    headers=[
                        ("Location", "/cz/"),
                        ("Set-Cookie", f"PHPSESSID={sid}; path=/; HttpOnly"),
                        ("Set-Cookie", "nette-samesite=1; path=/; HttpOnly"),
                    ],
                )
            if self._authed(request):
                return httpx.Response(302, headers={"Location": "/cz/"})
            return httpx.Response(200, html=SIGNIN_HTML)
        if not self._authed(request):
            return httpx.Response(302, headers={"Location": "/cz/sign/in?backlink=x"})
        if path == "/cz/":
            return httpx.Response(200, html=HOME_HTML)
        if path.startswith("/cz/domena/"):
            return httpx.Response(200, html=f'<a href="/cz/sign/out"></a><p>page {path} {request.url.query.decode()}</p>')
        return httpx.Response(404, html="<h1>Not found</h1>")


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def site():
    return FakeSite()


@pytest.fixture
def clock():
    return FakeClock()


def make_client(site, clock, tmp_path, **kwargs):
    kwargs.setdefault("cookie_path", tmp_path / "cookies.json")
    kwargs.setdefault("rate_limit_seconds", 1.5)
    return FinecimClient(
        kwargs.pop("credentials", CREDS),
        transport=httpx.MockTransport(site),
        sleep=clock.sleep,
        clock=clock.clock,
        **kwargs,
    )


# -- pure helpers ------------------------------------------------------------------------


def test_parse_login_form_fixture():
    form = parse_login_form(SIGNIN_HTML)
    assert form["action"] == "/cz/sign/in"
    assert form["fields"] == {
        "_token_": "aqzz8mcz2zKlgU5SF/xBXNMmotkIetPqTzVlQ=",
        "_do": "signIn-signInForm-submit",
    }


def test_parse_login_form_missing():
    with pytest.raises(FinecimAuthError):
        parse_login_form(HOME_HTML)


def test_looks_like_login_page():
    assert FinecimClient.looks_like_login_page(f"{BASE_URL}/cz/sign/in?backlink=abc", "")
    assert FinecimClient.looks_like_login_page(f"{BASE_URL}/cz/", SIGNIN_HTML)
    assert not FinecimClient.looks_like_login_page(f"{BASE_URL}/cz/", HOME_HTML)


def test_absolute():
    assert FinecimClient.absolute("/cz/domena/ucty/news") == f"{BASE_URL}/cz/domena/ucty/news"
    assert FinecimClient.absolute("cz/x") == f"{BASE_URL}/cz/x"
    assert FinecimClient.absolute("https://example.org/a") == "https://example.org/a"


def test_forbidden_urls():
    assert is_forbidden_url(f"{BASE_URL}/cz/domena/ucty/news/1?do=favorite")
    assert is_forbidden_url(f"{BASE_URL}/cz/domena/ucty/news/1?do=readLater")
    assert is_forbidden_url(f"{BASE_URL}/cz/domena/ucty/news/1?do=exportToPdf")
    assert is_forbidden_url(f"{BASE_URL}/cz/x?do=askFerda")
    assert is_forbidden_url(f"{BASE_URL}/cz/sign/out")
    assert not is_forbidden_url(f"{BASE_URL}/cz/domena/ucty/campaign/5?type=1&do=campaignCreatives")
    assert not is_forbidden_url(f"{BASE_URL}/cz/domena/ucty/news?step=96&page=2")


def test_forbidden_url_is_never_requested(site, clock, tmp_path):
    with make_client(site, clock, tmp_path) as client, pytest.raises(FinecimForbiddenURLError):
        client.get("/cz/domena/ucty/news/1?do=favorite")
    assert site.requests == []


# -- login -------------------------------------------------------------------------------


def test_get_logs_in_automatically(site, clock, tmp_path):
    with make_client(site, clock, tmp_path) as client:
        html = client.get("/cz/domena/ucty/news", params={"step": 96})
    assert "page /cz/domena/ucty/news step=96" in html
    assert site.logins == 1
    post = site.posts[0]
    assert set(post) == {"username", "passwd", "remember", "login", "_token_", "_do"}
    assert all("Mozilla/5.0" in r.headers["user-agent"] for r in site.requests)


def test_login_explicit_and_is_logged_in(site, clock, tmp_path):
    with make_client(site, clock, tmp_path) as client:
        assert client.is_logged_in() is False
        client.login()
        assert client.is_logged_in() is True
        client.login()  # already valid: sign-in GET redirects home, no second POST
    assert site.logins == 1 and len(site.posts) == 1


def test_wrong_password_raises(site, clock, tmp_path):
    bad = Credentials(CREDS.username, "wrong-password", "test")
    with make_client(site, clock, tmp_path, credentials=bad) as client:
        with pytest.raises(FinecimAuthError) as excinfo:
            client.login()
        assert "wrong-password" not in str(excinfo.value)
        with pytest.raises(FinecimAuthError):
            client.get("/cz/domena/ucty/news")
    assert site.logins == 0


def test_session_expiry_triggers_one_relogin(site, clock, tmp_path):
    with make_client(site, clock, tmp_path) as client:
        client.get("/cz/domena/ucty/news")
        assert site.logins == 1
        site.expire_sessions()
        html = client.get("/cz/domena/ucty/campaign")
        assert "campaign" in html
        assert site.logins == 2
        client.get("/cz/domena/ucty/mystery-shopping")
    assert site.logins == 2


def test_persistent_login_redirect_raises_after_one_retry(site, clock, tmp_path):
    with make_client(site, clock, tmp_path) as client:
        client.login()
        # The content page keeps bouncing to the sign-in page even right after a login.
        site.overrides["/cz/domena/ucty/news"] = [
            httpx.Response(200, html=SIGNIN_HTML),
            httpx.Response(200, html=SIGNIN_HTML),
        ]
        site.expire_sessions()
        with pytest.raises(FinecimAuthError):
            client.get("/cz/domena/ucty/news")
    assert site.logins == 2


def test_lazy_credentials_loaded_only_on_login(site, clock, tmp_path, monkeypatch):
    monkeypatch.setenv("FINECIM_USERNAME", CREDS.username)
    monkeypatch.setenv("FINECIM_PASSWORD", CREDS.password)
    client = FinecimClient(
        None, cookie_path=None, transport=httpx.MockTransport(site), sleep=clock.sleep, clock=clock.clock
    )
    with client:
        assert "page" in client.get("/cz/domena/ucty/news")
    assert site.logins == 1


# -- rate limit, retries, errors ---------------------------------------------------------


def test_rate_limiter_spacing(site, clock, tmp_path):
    with make_client(site, clock, tmp_path, rate_limit_seconds=2.0) as client:
        client.login()
        clock.sleeps.clear()
        start = clock.now
        times = []
        for i in range(4):
            client.get(f"/cz/domena/ucty/news/{i}")
            times.append(clock.now)
    # Each request waits out the remaining interval since the previous one.
    assert all(s == pytest.approx(2.0) for s in clock.sleeps)
    assert len(clock.sleeps) == 4
    assert times[-1] - start == pytest.approx(8.0)


def test_rate_limiter_does_not_sleep_when_time_passed(site, clock, tmp_path):
    with make_client(site, clock, tmp_path, rate_limit_seconds=1.5) as client:
        client.login()
        clock.sleeps.clear()
        clock.now += 10
        client.get("/cz/domena/ucty/news")
        assert clock.sleeps == []
        clock.now += 0.5
        client.get("/cz/domena/ucty/news")
        assert clock.sleeps == [pytest.approx(1.0)]


def test_retry_500_then_200(site, clock, tmp_path):
    with make_client(site, clock, tmp_path) as client:
        client.login()
        site.overrides["/cz/domena/ucty/news"] = [httpx.Response(500), httpx.Response(503)]
        before = len(site.requests)
        html = client.get("/cz/domena/ucty/news")
    assert "page /cz/domena/ucty/news" in html
    assert len(site.requests) - before == 3
    assert len(clock.sleeps) >= 2


def test_retry_transport_error(site, clock, tmp_path):
    with make_client(site, clock, tmp_path) as client:
        client.login()
        site.overrides["/cz/domena/ucty/news"] = [httpx.ConnectError("boom")]
        assert "page" in client.get("/cz/domena/ucty/news")


def test_5xx_exhausts_retries(site, clock, tmp_path):
    with make_client(site, clock, tmp_path, max_retries=3) as client:
        client.login()
        site.overrides["/cz/domena/ucty/news"] = [httpx.Response(502) for _ in range(5)]
        before = len(site.requests)
        with pytest.raises(FinecimHTTPError) as excinfo:
            client.get("/cz/domena/ucty/news")
    assert excinfo.value.status_code == 502
    assert len(site.requests) - before == 4  # 1 attempt + 3 retries


def test_404_raises_http_error(site, clock, tmp_path):
    with make_client(site, clock, tmp_path) as client:
        client.login()
        before = len(site.requests)
        with pytest.raises(FinecimHTTPError) as excinfo:
            client.get("/cz/nothing-here")
    assert excinfo.value.status_code == 404
    assert excinfo.value.url == f"{BASE_URL}/cz/nothing-here"
    assert len(site.requests) - before == 1  # no retries on 4xx


def test_get_fragment_is_get(site, clock, tmp_path):
    with make_client(site, clock, tmp_path) as client:
        html = client.get_fragment(f"{BASE_URL}/cz/domena/ucty/campaign/5?type=1&do=campaignCreatives")
    assert "do=campaignCreatives" in html


# -- cookies -----------------------------------------------------------------------------


def test_cookie_file_round_trip(site, clock, tmp_path):
    cookie_path = tmp_path / "nested" / "dir" / "cookies.json"
    with make_client(site, clock, tmp_path, cookie_path=cookie_path) as client:
        client.get("/cz/domena/ucty/news")
    assert site.logins == 1
    rows = json.loads(cookie_path.read_text(encoding="utf-8"))
    names = {r["name"] for r in rows}
    assert {"PHPSESSID", "nette-samesite"} <= names
    assert all(set(r) == {"name", "value", "domain", "path", "expires"} for r in rows)

    # A new client reuses the persisted session: no second login.
    with make_client(site, clock, tmp_path, cookie_path=cookie_path) as client2:
        assert client2.is_logged_in() is True
        client2.get("/cz/domena/ucty/campaign")
    assert site.logins == 1


def test_corrupt_cookie_file_is_ignored(site, clock, tmp_path):
    cookie_path = tmp_path / "cookies.json"
    cookie_path.write_text("{not json", encoding="utf-8")
    with make_client(site, clock, tmp_path, cookie_path=cookie_path) as client:
        assert "page" in client.get("/cz/domena/ucty/news")
    assert isinstance(json.loads(cookie_path.read_text(encoding="utf-8")), list)


def test_expired_cookies_are_not_loaded(site, clock, tmp_path):
    cookie_path = tmp_path / "cookies.json"
    site.sessions.add("old")
    cookie_path.write_text(
        json.dumps([{"name": "PHPSESSID", "value": "old", "domain": "www.finecim.cz", "path": "/", "expires": 1}]),
        encoding="utf-8",
    )
    with make_client(site, clock, tmp_path, cookie_path=cookie_path) as client:
        assert client.is_logged_in() is False


def test_no_cookie_path_writes_nothing(site, clock, tmp_path):
    with make_client(site, clock, tmp_path, cookie_path=None) as client:
        client.get("/cz/domena/ucty/news")
    assert list(tmp_path.iterdir()) == []


# -- hardening: 429 / Retry-After ---------------------------------------------------------


def _logged_in_quiet(site, clock, tmp_path, **kwargs):
    """A logged-in client whose next request needs no rate-limit wait."""
    client = make_client(site, clock, tmp_path, **kwargs)
    client.open()
    client.login()
    clock.now += 100
    clock.sleeps.clear()
    return client


def test_parse_retry_after():
    now = datetime(2026, 11, 5, 12, 0, 0, tzinfo=UTC)
    assert parse_retry_after("2", now=now) == 2.0
    assert parse_retry_after(" 7 ", now=now) == 7.0
    assert parse_retry_after("-3", now=now) == 0.0
    assert parse_retry_after(format_datetime(now + timedelta(seconds=30), usegmt=True), now=now) == 30.0
    assert parse_retry_after(format_datetime(now - timedelta(seconds=30), usegmt=True), now=now) == 0.0
    assert parse_retry_after(None) is None
    assert parse_retry_after("") is None
    assert parse_retry_after("soon-ish") is None


def test_429_with_retry_after_then_200(site, clock, tmp_path):
    client = _logged_in_quiet(site, clock, tmp_path)
    with client:
        site.overrides["/cz/domena/ucty/news"] = [httpx.Response(429, headers={"Retry-After": "2"})]
        before = len(site.requests)
        html = client.get("/cz/domena/ucty/news")
    assert "page /cz/domena/ucty/news" in html
    assert clock.sleeps == [pytest.approx(2.0)]
    assert len(site.requests) - before == 2


def test_429_retry_after_http_date_is_capped(site, clock, tmp_path):
    far = format_datetime(datetime.now(UTC) + timedelta(hours=2), usegmt=True)
    client = _logged_in_quiet(site, clock, tmp_path)
    with client:
        site.overrides["/cz/domena/ucty/news"] = [httpx.Response(429, headers={"Retry-After": far})]
        assert "page" in client.get("/cz/domena/ucty/news")
    assert clock.sleeps == [pytest.approx(MAX_RETRY_AFTER_SECONDS)]


def test_503_with_retry_after_is_honoured(site, clock, tmp_path):
    client = _logged_in_quiet(site, clock, tmp_path)
    with client:
        site.overrides["/cz/domena/ucty/news"] = [httpx.Response(503, headers={"Retry-After": "5"})]
        assert "page" in client.get("/cz/domena/ucty/news")
    assert clock.sleeps == [pytest.approx(5.0)]


def test_429_without_header_backs_off_exponentially(site, clock, tmp_path):
    client = _logged_in_quiet(site, clock, tmp_path, rate_limit_seconds=1.5)
    with client:
        site.overrides["/cz/domena/ucty/news"] = [httpx.Response(429), httpx.Response(429)]
        assert "page" in client.get("/cz/domena/ucty/news")
    assert clock.sleeps == [pytest.approx(1.5), pytest.approx(3.0)]


def test_429_forever_raises(site, clock, tmp_path):
    client = _logged_in_quiet(site, clock, tmp_path, max_retries=2)
    with client:
        site.overrides["/cz/domena/ucty/news"] = [
            httpx.Response(429, headers={"Retry-After": "2"}) for _ in range(10)
        ]
        before = len(site.requests)
        with pytest.raises(FinecimHTTPError) as excinfo:
            client.get("/cz/domena/ucty/news")
    assert excinfo.value.status_code == 429
    assert len(site.requests) - before == 3  # 1 attempt + 2 retries
    assert clock.sleeps == [pytest.approx(2.0), pytest.approx(2.0)]


# -- hardening: forbidden-URL guard -------------------------------------------------------


@pytest.mark.parametrize("params", [
    {"do": "favorite"},
    {"do": "article-readLater"},
    {"do": "exportToPdf"},
    {"do": "askFerda"},
    {"_do": "favorite"},
    {"backlink": "/cz/sign/out"},
    {"next": "/cz/domena/ucty/early-warnings"},
    {"redirect": "/cz/x?do=readLater"},
    {"do": ["campaignCreatives", "favorite"]},
])
def test_forbidden_params_are_never_requested(site, clock, tmp_path, params):
    with make_client(site, clock, tmp_path) as client, pytest.raises(FinecimForbiddenURLError):
        client.get("/cz/domena/ucty/news/1", params=params)
    assert site.requests == []


def test_allowed_params_pass_the_guard(site, clock, tmp_path):
    with make_client(site, clock, tmp_path) as client:
        html = client.get("/cz/domena/ucty/campaign/5", params={"type": 1, "do": "campaignCreatives"})
    assert "do=campaignCreatives" in html


@pytest.mark.parametrize("location", [
    "/cz/sign/out",
    "/cz/domena/ucty/news/1?do=favorite",
    "/cz/domena/ucty/news/1?do=readLater",
    "/cz/domena/ucty/news/1?do=exportToPdf",
    "/cz/x?do=askFerda",
    "/cz/domena/ucty/early-warnings",
])
def test_redirect_to_forbidden_url_raises_and_is_not_followed(site, clock, tmp_path, location):
    with make_client(site, clock, tmp_path) as client:
        client.login()
        site.overrides["/cz/domena/ucty/news"] = [httpx.Response(302, headers={"Location": location})]
        before = len(site.requests)
        with pytest.raises(FinecimForbiddenURLError):
            client.get("/cz/domena/ucty/news")
    hops = [str(r.url) for r in site.requests[before:]]
    assert hops == [f"{BASE_URL}/cz/domena/ucty/news"]  # the forbidden target was never sent


def test_final_url_check_discards_forbidden_landing(tmp_path, clock):
    """Even if a transport hands back a response whose URL is forbidden (no hop went
    through the request hook), the body is discarded and the error raised."""

    class LandingTransport(httpx.BaseTransport):
        def handle_request(self, request):
            return httpx.Response(200, html=HOME_HTML + "<p>secret body</p>")

    client = FinecimClient(CREDS, cookie_path=None, transport=LandingTransport(),
                           sleep=clock.sleep, clock=clock.clock)
    with client:
        original = client.http.request

        def fake_request(method, url, **kwargs):
            response = original(method, url, **kwargs)
            response.request = httpx.Request("GET", f"{BASE_URL}/cz/sign/out")
            return response

        client.http.request = fake_request
        with pytest.raises(FinecimForbiddenURLError):
            client.get("/cz/domena/ucty/news")


# -- hardening: get_fragment (Nette AJAX) -------------------------------------------------


def test_parse_nette_snippets():
    payload = json.dumps({"state": [], "snippets": {"snippet--a": "<div>A</div>", "snippet--b": "<div>B</div>"}})
    assert parse_nette_snippets(payload) == "<div>A</div>\n<div>B</div>"
    assert parse_nette_snippets("<div>html</div>") is None
    assert parse_nette_snippets(json.dumps({"redirect": "/cz/"})) is None
    assert parse_nette_snippets("{broken") is None


def test_get_fragment_sends_ajax_header_and_returns_html(site, clock, tmp_path):
    url = f"{BASE_URL}/cz/domena/ucty/campaign/5?type=1&do=campaignCreatives"
    with make_client(site, clock, tmp_path) as client:
        html = client.get_fragment(url)
        last = site.requests[-1]
        client.get("/cz/domena/ucty/news")
        plain = site.requests[-1]
    assert "do=campaignCreatives" in html
    assert last.headers.get("x-requested-with") == "XMLHttpRequest"
    assert "x-requested-with" not in plain.headers  # only fragments are AJAX requests


def test_get_fragment_json_snippets_payload(site, clock, tmp_path):
    payload = {"snippets": {"snippet-creatives-list": '<div class="c">one</div>',
                            "snippet-creatives-more": '<div class="c">two</div>'}}
    with make_client(site, clock, tmp_path) as client:
        client.login()
        site.overrides["/cz/domena/ucty/campaign/5"] = [httpx.Response(200, json=payload)]
        html = client.get_fragment("/cz/domena/ucty/campaign/5?type=1&do=campaignCreatives")
    assert html == '<div class="c">one</div>\n<div class="c">two</div>'


def test_get_fragment_json_redirect_to_sign_in_relogs(site, clock, tmp_path):
    with make_client(site, clock, tmp_path) as client:
        client.login()
        site.overrides["/cz/domena/ucty/campaign/5"] = [
            httpx.Response(200, json={"redirect": f"{BASE_URL}/cz/sign/in?backlink=abc"}),
        ]
        site.expire_sessions()
        html = client.get_fragment("/cz/domena/ucty/campaign/5?type=1&do=campaignCreatives")
    assert "do=campaignCreatives" in html
    assert site.logins == 2


# -- hardening: login keeps the backlink --------------------------------------------------


def test_login_posts_to_url_with_live_backlink(site, clock, tmp_path):
    site.overrides["/cz/sign/in"] = [httpx.Response(302, headers={"Location": "/cz/sign/in?backlink=k7q2"})]
    with make_client(site, clock, tmp_path) as client:
        client.login()
    post = next(r for r in site.requests if r.method == "POST")
    assert str(post.url) == f"{BASE_URL}/cz/sign/in?backlink=k7q2"
    assert site.logins == 1


def test_login_action_resolution():
    page = f"{BASE_URL}/cz/sign/in?backlink=abc&other=1"
    assert FinecimClient._login_action(page, "/cz/sign/in") == f"{BASE_URL}/cz/sign/in?backlink=abc"
    assert FinecimClient._login_action(page, "/cz/sign/in?backlink=zzz") == f"{BASE_URL}/cz/sign/in?backlink=zzz"
    assert FinecimClient._login_action(page, "") == page
    assert FinecimClient._login_action(f"{BASE_URL}/cz/sign/in", "/cz/sign/in") == f"{BASE_URL}/cz/sign/in"


# -- hardening: credentials errors propagate ----------------------------------------------


def test_credentials_error_during_auto_login_propagates_unchanged(site, clock, tmp_path, monkeypatch):
    err = CredentialsError("FINeCIM credentials not found (test)")

    def boom(*_args, **_kwargs):
        raise err

    monkeypatch.setattr(client_mod, "load_credentials", boom)
    client = FinecimClient(None, cookie_path=None, transport=httpx.MockTransport(site),
                           sleep=clock.sleep, clock=clock.clock)
    with client, pytest.raises(CredentialsError) as excinfo:
        client.get("/cz/domena/ucty/news")
    assert excinfo.value is err
    assert site.posts == []


# -- review follow-ups --------------------------------------------------------------------


def test_auto_login_posts_to_redirected_backlink_and_fetches_sign_in_once(site, clock, tmp_path):
    """The normal flow (spec section 1): an unauthenticated content GET is redirected to
    /cz/sign/in?backlink=..., and the login POST keeps that backlink."""
    with make_client(site, clock, tmp_path) as client:
        html = client.get("/cz/domena/ucty/news")
    assert "page /cz/domena/ucty/news" in html
    hops = [(r.method, str(r.url)) for r in site.requests]
    assert hops == [
        ("GET", f"{BASE_URL}/cz/domena/ucty/news"),
        ("GET", f"{BASE_URL}/cz/sign/in?backlink=x"),
        ("POST", f"{BASE_URL}/cz/sign/in?backlink=x"),
        ("GET", f"{BASE_URL}/cz/"),
        ("GET", f"{BASE_URL}/cz/domena/ucty/news"),
    ]
    assert site.logins == 1


def test_auto_login_from_ajax_redirect_keeps_backlink(site, clock, tmp_path):
    with make_client(site, clock, tmp_path) as client:
        client.login()
        site.overrides["/cz/domena/ucty/campaign/5"] = [
            httpx.Response(200, json={"redirect": f"{BASE_URL}/cz/sign/in?backlink=abc"}),
        ]
        site.expire_sessions()
        client.get_fragment("/cz/domena/ucty/campaign/5?type=1&do=campaignCreatives")
    posts = [str(r.url) for r in site.requests if r.method == "POST"]
    assert posts[-1] == f"{BASE_URL}/cz/sign/in?backlink=abc"
    assert site.logins == 2


def test_login_ignores_foreign_signin_url(site, clock, tmp_path):
    with make_client(site, clock, tmp_path) as client:
        client.login("https://evil.example/cz/sign/in?backlink=zz")
    assert all(r.url.host == "www.finecim.cz" for r in site.requests)
    post = next(r for r in site.requests if r.method == "POST")
    assert str(post.url) == f"{BASE_URL}/cz/sign/in"


@pytest.mark.parametrize("params", [
    [("do", "favorite")],
    (("step", "96"), ("do", "readLater")),
    "do=favorite",
    "?step=1&do=exportToPdf",
    b"do=askFerda",
    httpx.QueryParams({"do": "favorite"}),
])
def test_forbidden_params_in_any_shape_raise_forbidden_error(site, clock, tmp_path, params):
    with make_client(site, clock, tmp_path) as client, pytest.raises(FinecimForbiddenURLError):
        client.get("/cz/domena/ucty/news/1", params=params)
    assert site.requests == []


@pytest.mark.parametrize("params", [
    [("step", "96"), ("page", "2")],
    "step=96&page=2",
    httpx.QueryParams({"step": "96"}),
])
def test_allowed_params_in_any_shape_pass_the_guard(site, clock, tmp_path, params):
    with make_client(site, clock, tmp_path) as client:
        html = client.get("/cz/domena/ucty/news", params=params)
    assert "step=96" in html


def test_forbidden_signal_in_post_body_is_never_sent(site, clock, tmp_path):
    with make_client(site, clock, tmp_path) as client, pytest.raises(FinecimForbiddenURLError):
        client._request("POST", f"{BASE_URL}/cz/domena/ucty/news/1", data={"_do": "favorite-toggle"})
    assert site.requests == []


def test_post_body_free_text_is_not_pattern_matched(site, clock, tmp_path):
    odd = Credentials(CREDS.username, "x/sign/out?do=favorite", "test")
    with make_client(site, clock, tmp_path, credentials=odd) as client, pytest.raises(FinecimAuthError):
        client.login()  # wrong password, but the POST itself is sent
    assert len(site.posts) == 1


def test_get_fragment_json_with_utf8_bom(site, clock, tmp_path):
    body = "\ufeff" + json.dumps({"snippets": {"snippet-a": "<b>y</b>"}})
    with make_client(site, clock, tmp_path) as client:
        client.login()
        site.overrides["/cz/domena/ucty/campaign/5"] = [
            httpx.Response(200, content=body.encode("utf-8"),
                           headers={"Content-Type": "application/json; charset=utf-8"}),
        ]
        html = client.get_fragment("/cz/domena/ucty/campaign/5?type=1&do=campaignCreatives")
    assert html == "<b>y</b>"


@pytest.mark.parametrize("path", [
    "/cz/sign//out",
    "/cz/sign/out.php",
    "/cz/early_warnings",
    "/cz/Early-Warning/",
    "/cz/x?DO=favorite",
    "/cz/x?_DO=readLater",
])
def test_forbidden_url_variants(path):
    assert is_forbidden_url(f"{BASE_URL}{path}")


def test_forbidden_url_variants_do_not_overmatch():
    assert not is_forbidden_url(f"{BASE_URL}/cz/sign/outlook")
    assert not is_forbidden_url(f"{BASE_URL}/cz/domena/ucty/news?title=early")


def test_parse_retry_after_rejects_non_finite():
    assert parse_retry_after("nan") is None
    assert parse_retry_after("inf") is None


# -- hardening: credentials never leave www.finecim.cz ------------------------------------


EVIL = "https://evil.example"


def _password_left_finecim(site) -> bool:
    """True if any request to a host other than www.finecim.cz was a POST or carried the
    password in its body or URL."""
    for request in site.requests:
        if request.url.host == "www.finecim.cz":
            continue
        if request.method == "POST" or CREDS.password in (request.content or b"").decode(
                "utf-8", "replace") or CREDS.password in str(request.url):
            return True
    return False


def _route_by_host(site, foreign):
    """Wrap FakeSite so requests to a foreign host are answered by ``foreign``."""
    def handler(request):
        if request.url.host != "www.finecim.cz":
            site.requests.append(request)
            return foreign(request)
        return site(request)
    return handler


def _make_routed_client(handler, clock, tmp_path):
    return FinecimClient(CREDS, cookie_path=tmp_path / "cookies.json", rate_limit_seconds=1.5,
                         transport=httpx.MockTransport(handler), sleep=clock.sleep,
                         clock=clock.clock)


def test_off_host_redirect_to_sign_in_never_receives_credentials(site, clock, tmp_path):
    site.overrides["/cz/domena/ucty/r"] = [
        httpx.Response(302, headers={"Location": f"{EVIL}/cz/sign/in?backlink=q"}),
    ]
    handler = _route_by_host(site, lambda request: httpx.Response(200, html=SIGNIN_HTML))
    with _make_routed_client(handler, clock, tmp_path) as client:
        html = client.get("/cz/domena/ucty/r")
    assert "page /cz/domena/ucty/r" in html
    assert not _password_left_finecim(site)
    posts = [str(r.url) for r in site.requests if r.method == "POST"]
    assert posts == [f"{BASE_URL}/cz/sign/in"]
    assert site.logins == 1


def test_off_host_page_with_login_form_never_receives_credentials(site, clock, tmp_path):
    handler = _route_by_host(site, lambda request: httpx.Response(200, html=SIGNIN_HTML))
    client = _make_routed_client(handler, clock, tmp_path)
    with client, pytest.raises(FinecimAuthError):  # the foreign page keeps serving the form
        client.get(f"{EVIL}/landing")
    assert not _password_left_finecim(site)
    assert all(r.url.host == "www.finecim.cz" for r in site.requests if r.method == "POST")


def test_off_host_fragment_with_login_form_never_receives_credentials(site, clock, tmp_path):
    handler = _route_by_host(site, lambda request: httpx.Response(200, html=SIGNIN_HTML))
    client = _make_routed_client(handler, clock, tmp_path)
    with client, pytest.raises(FinecimAuthError):
        client.get_fragment(f"{EVIL}/frag")
    assert not _password_left_finecim(site)


def test_login_does_not_reuse_off_host_page(site, clock, tmp_path):
    foreign = httpx.Response(200, html=SIGNIN_HTML,
                             request=httpx.Request("GET", f"{EVIL}/cz/sign/in?backlink=q"))
    with make_client(site, clock, tmp_path) as client:
        client.login(f"{EVIL}/cz/sign/in?backlink=q", page=foreign)
    assert [(r.method, str(r.url)) for r in site.requests][:2] == [
        ("GET", f"{BASE_URL}/cz/sign/in"),
        ("POST", f"{BASE_URL}/cz/sign/in"),
    ]


def test_off_host_form_action_is_refused(site, clock, tmp_path):
    evil_form = SIGNIN_HTML.replace('action="/cz/sign/in"', f'action="{EVIL}/cz/sign/in"')
    site.overrides["/cz/sign/in"] = [httpx.Response(200, html=evil_form)]
    client = make_client(site, clock, tmp_path)
    with client, pytest.raises(FinecimAuthError, match="off-host"):
        client.login()
    assert not any(r.method == "POST" for r in site.requests)


def test_get_fragment_json_without_snippets_returns_empty(site, clock, tmp_path):
    with make_client(site, clock, tmp_path) as client:
        client.login()
        site.overrides["/cz/domena/ucty/campaign/5"] = [
            httpx.Response(200, json={"state": []}),
            httpx.Response(200, json={"redirect": f"{BASE_URL}/cz/domena/ucty/"}),
        ]
        assert client.get_fragment("/cz/domena/ucty/campaign/5?do=campaignCreatives") == ""
        assert client.get_fragment("/cz/domena/ucty/campaign/5?do=campaignCreatives") == ""
