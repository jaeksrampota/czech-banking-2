import pytest
from src.security.urls import UnsafeURLError, validate_url


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/",
        "http://127.0.0.1/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",  # AWS metadata (link-local)
        "http://[::1]/",
    ],
)
def test_rejects_internal_targets(url):
    with pytest.raises(UnsafeURLError):
        validate_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/",
        "file:///etc/passwd",
        "gopher://example.com/",
        "",
    ],
)
def test_rejects_disallowed_schemes_and_empty(url):
    with pytest.raises(UnsafeURLError):
        validate_url(url)


def test_accepts_public_https_host():
    # Uses a well-known public IP literal so we don't depend on DNS in tests.
    assert validate_url("https://1.1.1.1/") == "https://1.1.1.1/"
