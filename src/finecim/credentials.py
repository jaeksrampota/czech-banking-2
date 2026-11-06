"""Resolve the FINeCIM login credentials without ever exposing them.

Resolution order (first complete pair wins):

1. environment variables ``FINECIM_USERNAME`` / ``FINECIM_PASSWORD``;
2. the explicit ``env_file`` argument, or the file named by ``FINECIM_ENV_FILE``;
3. ``<repo root>/.env``;
4. ``~/.finecim.env``.

Files are ``KEY=VALUE`` lines (UTF-8, BOM tolerated) with ``#`` comments, an optional
``export`` prefix and optional single or double quotes around the value. An unquoted
value ends at a ``#`` preceded by whitespace (quote the value if it contains `` #``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "ENV_FILE_VAR",
    "PASSWORD_VAR",
    "USERNAME_VAR",
    "Credentials",
    "CredentialsError",
    "load_credentials",
    "parse_env_file",
]

USERNAME_VAR = "FINECIM_USERNAME"
PASSWORD_VAR = "FINECIM_PASSWORD"
ENV_FILE_VAR = "FINECIM_ENV_FILE"

#: ``<repo root>/.env`` (module attribute so tests can point it elsewhere).
REPO_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
HOME_ENV_NAME = ".finecim.env"


class CredentialsError(RuntimeError):
    """No usable FINeCIM credentials were found. The message lists the places searched."""


@dataclass(frozen=True)
class Credentials:
    username: str
    password: str
    source: str  # "env" | path of the file it came from

    def __repr__(self) -> str:
        return f"Credentials(username={self.username!r}, password='***', source={self.source!r})"

    __str__ = __repr__


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        inner = value[1:-1]
        if value[0] == '"':
            inner = inner.replace('\\"', '"').replace("\\\\", "\\")
        return inner
    if value[:1] in ("'", '"'):
        # Quoted value followed by an inline comment: KEY="abc"  # note
        quote = value[0]
        end = value.find(quote, 1)
        if end > 0 and (value[end + 1 :].strip() == "" or value[end + 1 :].lstrip().startswith("#")):
            return value[1:end]
        return value
    # Unquoted: strip an inline comment introduced by whitespace + '#'.
    for i, ch in enumerate(value):
        if ch == "#" and i > 0 and value[i - 1] in " \t":
            return value[:i].rstrip()
    return value


def parse_env_file(path: str | os.PathLike) -> dict[str, str]:
    """Parse a KEY=VALUE file into a dict. Malformed lines are ignored silently
    (their content is never echoed, as it may contain a secret)."""
    text = Path(path).read_text(encoding="utf-8-sig")
    result: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export ") or line.startswith("export\t"):
            line = line[len("export") :].lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not key:
            continue
        result[key] = _unquote(value)
    return result


def _from_file(path: Path) -> tuple[Credentials | None, str]:
    """Return (credentials or None, short status for the error message)."""
    if not path.is_file():
        return None, "not found"
    try:
        values = parse_env_file(path)
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"unreadable ({type(exc).__name__})"
    username = values.get(USERNAME_VAR, "").strip()
    password = values.get(PASSWORD_VAR, "")
    if username and password:
        return Credentials(username=username, password=password, source=str(path)), "ok"
    return None, f"no {USERNAME_VAR}/{PASSWORD_VAR}"


def load_credentials(env_file: str | os.PathLike | None = None) -> Credentials:
    """Resolve credentials (see module docstring for the order).

    Raises CredentialsError naming the places searched, never echoing any value."""
    searched: list[str] = []

    username = os.environ.get(USERNAME_VAR, "").strip()
    password = os.environ.get(PASSWORD_VAR, "")
    if username and password:
        return Credentials(username=username, password=password, source="env")
    searched.append(f"environment variables {USERNAME_VAR}/{PASSWORD_VAR} (not set)")

    candidates: list[Path] = []
    explicit = env_file if env_file is not None else os.environ.get(ENV_FILE_VAR) or None
    if explicit is not None:
        candidates.append(Path(explicit).expanduser())
    candidates.append(Path(REPO_ENV_FILE))
    candidates.append(Path.home() / HOME_ENV_NAME)

    seen: set[str] = set()
    for path in candidates:
        key = os.path.normcase(str(path.absolute()))
        if key in seen:
            continue
        seen.add(key)
        creds, status = _from_file(path)
        if creds is not None:
            return creds
        searched.append(f"{path} ({status})")

    raise CredentialsError(
        "FINeCIM credentials not found. Searched: " + "; ".join(searched)
        + f". Set {USERNAME_VAR} and {PASSWORD_VAR} in the environment or in one of these files."
    )
