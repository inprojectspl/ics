"""Web Push delivery (RFC 8030) with `aes128gcm` payload encryption (RFC 8291).

The endpoint comes from the browser, so it is untrusted: only known push
services are contacted, otherwise the worker could be pointed at an internal
host.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from typing import Final, Literal
from urllib.parse import urlsplit

import http_ece
import httpx
import orjson
from cryptography.hazmat.primitives.asymmetric import ec

from app.config import Settings
from app.util import is_host_locked_https

from . import vapid

logger = logging.getLogger("ics.notifications.webpush")

_ALLOWED_HOSTS: Final[frozenset[str]] = frozenset(
    {
        "fcm.googleapis.com",
        "updates.push.services.mozilla.com",
        "web.push.apple.com",
    }
)
_ALLOWED_SUFFIXES: Final[tuple[str, ...]] = (".notify.windows.com", ".push.apple.com")
_TTL_SECONDS: Final[int] = 86_400
_TIMEOUT_SECONDS: Final[float] = 5.0

PushResult = Literal["ok", "gone", "failed"]


@dataclass(frozen=True, slots=True)
class PushTarget:
    endpoint: str
    p256dh: str
    auth: str


_clients: dict[int, httpx.AsyncClient] = {}


def client() -> httpx.AsyncClient:
    """One pooled client per event loop: push services keep TLS connections
    alive, so every event after the first skips the handshake."""
    loop_id = id(asyncio.get_running_loop())
    found = _clients.get(loop_id)
    if found is None or found.is_closed:
        _clients.clear()
        found = _clients[loop_id] = httpx.AsyncClient(timeout=_TIMEOUT_SECONDS)
    return found


async def close_client() -> None:
    for c in list(_clients.values()):
        await c.aclose()
    _clients.clear()


def is_configured(settings: Settings) -> bool:
    return bool(settings.vapid_private_key and settings.vapid_subject)


def endpoint_allowed(endpoint: str) -> bool:
    return is_host_locked_https(endpoint, _ALLOWED_HOSTS, _ALLOWED_SUFFIXES)


def topic_of(tag: str) -> str:
    """The `Topic` header allows 32 URL-safe base64 characters."""
    return vapid.b64url(hashlib.sha256(tag.encode()).digest())[:32]


def encrypt(payload: bytes, target: PushTarget) -> bytes:
    return http_ece.encrypt(
        payload,
        private_key=ec.generate_private_key(ec.SECP256R1()),
        dh=vapid.b64url_decode(target.p256dh),
        auth_secret=vapid.b64url_decode(target.auth),
        version="aes128gcm",
    )


async def send(
    client: httpx.AsyncClient,
    target: PushTarget,
    message: dict[str, str | None],
    *,
    settings: Settings,
) -> PushResult:
    if not endpoint_allowed(target.endpoint):
        logger.warning("push endpoint not allowed: host=%s", urlsplit(target.endpoint).hostname)
        return "gone"
    try:
        body = encrypt(orjson.dumps(message), target)
        response = await client.post(
            target.endpoint,
            content=body,
            headers={
                "Authorization": vapid.authorization(
                    target.endpoint, settings.vapid_private_key, settings.vapid_subject
                ),
                "Content-Encoding": "aes128gcm",
                "Content-Type": "application/octet-stream",
                "TTL": str(_TTL_SECONDS),
                "Urgency": "normal",
                "Topic": topic_of(message.get("tag") or ""),
            },
            timeout=_TIMEOUT_SECONDS,
        )
    except Exception as e:
        logger.warning("push send failed: %s", type(e).__name__)
        return "failed"
    if response.status_code in (404, 410):
        return "gone"
    if response.status_code >= 400:
        logger.warning("push rejected: status=%s", response.status_code)
        return "failed"
    return "ok"
