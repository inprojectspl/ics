"""VAPID keys (RFC 8292) for Web Push.

`ICS_VAPID_PRIVATE_KEY` is the base64url private scalar of a P-256 key (the
format of `web-push generate-vapid-keys` and `python -m app.cli
vapid-keygen`); the public key the browser needs is derived from it.
"""

from __future__ import annotations

import base64
import time
from functools import lru_cache
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from joserfc import jwt
from joserfc.jwk import ECKey

_JWT_TTL_SECONDS = 12 * 3600


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


@lru_cache(maxsize=4)
def _private(private_b64: str) -> ec.EllipticCurvePrivateKey:
    scalar = int.from_bytes(b64url_decode(private_b64), "big")
    return ec.derive_private_key(scalar, ec.SECP256R1())


@lru_cache(maxsize=4)
def public_key(private_b64: str) -> str:
    """Uncompressed point, base64url: the browser's `applicationServerKey`."""
    point = (
        _private(private_b64)
        .public_key()
        .public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    )
    return b64url(point)


@lru_cache(maxsize=4)
def _jwk(private_b64: str) -> ECKey:
    return ECKey.import_key(_private(private_b64))


# (origin, key, subject) -> (header, expires at). A token is valid for
# `_JWT_TTL_SECONDS`; it is reused for most of that instead of signed per message.
_headers: dict[tuple[str, str, str], tuple[str, float]] = {}


def authorization(endpoint: str, private_b64: str, subject: str) -> str:
    """`Authorization` header for one push service origin."""
    parts = urlsplit(endpoint)
    origin = f"{parts.scheme}://{parts.netloc}"
    now = time.time()
    cached = _headers.get((origin, private_b64, subject))
    if cached is not None and cached[1] > now:
        return cached[0]
    claims = {"aud": origin, "exp": int(now) + _JWT_TTL_SECONDS, "sub": subject}
    token = jwt.encode({"alg": "ES256", "typ": "JWT"}, claims, _jwk(private_b64))
    header = f"vapid t={token}, k={public_key(private_b64)}"
    _headers[(origin, private_b64, subject)] = (header, now + _JWT_TTL_SECONDS / 2)
    return header


def generate() -> tuple[str, str]:
    """(private, public) pair for the configuration."""
    key = ec.generate_private_key(ec.SECP256R1())
    private_b64 = b64url(key.private_numbers().private_value.to_bytes(32, "big"))
    return private_b64, public_key(private_b64)
