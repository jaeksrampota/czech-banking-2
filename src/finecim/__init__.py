"""FINeCIM (www.finecim.cz) scraper: credentials, HTTP client, parsers and sync.

See finecim-research/SCRAPER-DESIGN.md. ``parsers`` and ``sync`` are imported from their
own modules (``src.finecim.parsers``, ``src.finecim.sync``).
"""

from src.finecim.client import (
    BASE_URL,
    DEFAULT_USER_AGENT,
    SIGN_IN_PATH,
    SIGN_OUT_MARKER,
    FinecimAuthError,
    FinecimClient,
    FinecimForbiddenURLError,
    FinecimHTTPError,
    is_forbidden_url,
    parse_login_form,
)
from src.finecim.credentials import (
    ENV_FILE_VAR,
    PASSWORD_VAR,
    USERNAME_VAR,
    Credentials,
    CredentialsError,
    load_credentials,
    parse_env_file,
)

__all__ = [
    "BASE_URL",
    "DEFAULT_USER_AGENT",
    "ENV_FILE_VAR",
    "PASSWORD_VAR",
    "SIGN_IN_PATH",
    "SIGN_OUT_MARKER",
    "USERNAME_VAR",
    "Credentials",
    "CredentialsError",
    "FinecimAuthError",
    "FinecimClient",
    "FinecimForbiddenURLError",
    "FinecimHTTPError",
    "is_forbidden_url",
    "load_credentials",
    "parse_env_file",
    "parse_login_form",
]
