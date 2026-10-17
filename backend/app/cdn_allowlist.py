"""Trusted-CDN hosts: `Settings.trusted_cdn_hosts` plus the admin-curated table.

The merged set is cached for 60 s for the scan hot path; admin writes call
`invalidate()`, so operators see no lag.
"""

from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import CdnAllowlist

_CACHE: dict[str, tuple[float, frozenset[str]]] = {}
_TTL_SECONDS = 60.0


def _cache_key(settings: Settings) -> str:
    # Settings with different baselines (e.g. in tests) must not share entries.
    return settings.trusted_cdn_hosts


async def trusted_hosts(session: AsyncSession, settings: Settings) -> frozenset[str]:
    """Return the effective lowercase host allowlist."""
    key = _cache_key(settings)
    now = time.monotonic()
    cached = _CACHE.get(key)
    if cached and (now - cached[0]) < _TTL_SECONDS:
        return cached[1]

    rows = (await session.execute(select(CdnAllowlist.host))).scalars().all()
    merged = settings.trusted_cdn_hosts_set | frozenset(h.lower() for h in rows)
    _CACHE[key] = (now, merged)
    return merged


def invalidate() -> None:
    """Drop the cache; called after add/remove writes so the next scan
    sees the new state immediately."""
    _CACHE.clear()


def is_acceptable_host(host: str) -> bool:
    """Shape check for an admin-added host: no ports, paths, wildcards or local
    addresses (subdomain matching is out of scope)."""
    if not host or " " in host or "/" in host or ":" in host:
        return False
    if host.startswith(".") or host.endswith("."):
        return False
    if host == "localhost" or host.startswith("127.") or host.startswith("10."):
        return False
    # Must contain a dot: bare `cloudflare` would let any subdomain in.
    if "." not in host:
        return False
    return True
