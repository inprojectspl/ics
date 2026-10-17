"""Small shared utilities used across routers."""

from __future__ import annotations

import hashlib
from collections.abc import Collection
from datetime import UTC, datetime
from urllib.parse import urlsplit

from fastapi import Request


def now() -> datetime:
    return datetime.now(UTC)


def short_sha256(value: str | bytes, length: int) -> str:
    """Truncated hex digest, for opaque identifiers and cache keys."""
    data = value.encode() if isinstance(value, str) else value
    return hashlib.sha256(data).hexdigest()[:length]


def ip_hash(request: Request) -> str:
    """Pseudonymous IP fingerprint for audit/rate-limit scoping."""
    ip = request.client.host if request.client else "unknown"
    return short_sha256(ip, 16)


def is_host_locked_https(url: str, hosts: Collection[str], suffixes: tuple[str, ...] = ()) -> bool:
    """`url` is https on the default port, without userinfo, and its host is
    one of `hosts` or ends with one of `suffixes`: the SSRF gate of outbound
    webhooks and push endpoints. Userinfo can mask the real host in some HTTP
    clients, and a non-standard port is a DNS rebinding trap with no
    legitimate use."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    if (
        parts.scheme != "https"
        or not host
        or parts.username is not None
        or parts.password is not None
    ):
        return False
    if port not in (None, 443):
        return False
    return host in hosts or (bool(suffixes) and host.endswith(suffixes))
