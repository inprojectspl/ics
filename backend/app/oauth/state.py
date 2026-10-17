"""HMAC-signed state token used in the OAuth /authorize consent flow. On top
of the Origin check in `app.csrf`, the signed state binds the consent POST
to the GET that produced it.

Format: `b64url(payload).b64url(hmac_sha256(secret, payload))`
"""

from __future__ import annotations

import binascii
import hmac
import secrets
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from hashlib import sha256

import orjson

from app.config import Settings

_TTL_SECONDS = 600  # 10 min: generous slack for slow human consent


def _b64u(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64u_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return urlsafe_b64decode(s + pad)


def issue(settings: Settings, payload: dict) -> str:
    body = {**payload, "_nonce": secrets.token_urlsafe(8), "_iat": int(time.time())}
    # OPT_SORT_KEYS: the HMAC must be reproducible (verify recomputes the same payload -> sig).
    raw = orjson.dumps(body, option=orjson.OPT_SORT_KEYS)
    sig = hmac.new(settings.secret_key.encode("utf-8"), raw, sha256).digest()
    return f"{_b64u(raw)}.{_b64u(sig)}"


def verify(settings: Settings, token: str) -> dict | None:
    """Return decoded payload if signature + TTL valid, else None."""
    try:
        body_b64, sig_b64 = token.split(".", 1)
        raw = _b64u_decode(body_b64)
        expected = hmac.new(settings.secret_key.encode("utf-8"), raw, sha256).digest()
        provided = _b64u_decode(sig_b64)
    except (ValueError, binascii.Error):
        return None
    if not hmac.compare_digest(expected, provided):
        return None
    try:
        data = orjson.loads(raw)
    except orjson.JSONDecodeError:
        return None
    iat = data.get("_iat")
    if not isinstance(iat, int) or time.time() - iat > _TTL_SECONDS:
        return None
    return data
