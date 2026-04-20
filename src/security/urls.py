"""SSRF guard for outbound HTTP requests.

Collectors accept URLs from YAML config and from scraped HTML. A misconfigured
career page or a maliciously crafted Justice.cz redirect could point at
localhost, a cloud-metadata endpoint, or an RFC1918 address. This module
rejects those before the request ever leaves the process.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

ALLOWED_SCHEMES = {"http", "https"}


class UnsafeURLError(ValueError):
    """Raised when a URL is rejected for security reasons."""


def validate_url(url: str) -> str:
    """Return the URL if it is safe to fetch; raise UnsafeURLError otherwise.

    Rejects: non-http(s) schemes, empty hosts, raw IP literals that resolve
    into private/loopback/link-local/metadata ranges, and hostnames whose
    DNS answers land in those same ranges.
    """
    if not url or not isinstance(url, str):
        raise UnsafeURLError("Empty URL")
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeURLError(f"Scheme not allowed: {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise UnsafeURLError(f"URL has no host: {url!r}")
    # If the host is a literal IP, check it directly.
    try:
        ip = ipaddress.ip_address(host)
        _reject_if_internal(ip, host)
        return url
    except ValueError:
        pass  # Not an IP literal — fall through to DNS resolution.
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"DNS resolution failed for {host!r}: {exc}") from exc
    for info in infos:
        sockaddr = info[4]
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        _reject_if_internal(ip, host)
    return url


def _reject_if_internal(ip: ipaddress._BaseAddress, host: str) -> None:
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        raise UnsafeURLError(
            f"Host {host!r} resolves to internal address {ip} — refusing to fetch"
        )
    # AWS/GCP/Azure metadata endpoints use the link-local range above, which
    # is already covered. 169.254.169.254 and fd00:ec2::254 fall into link-local.
