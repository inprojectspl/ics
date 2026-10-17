"""RSA keypair management and JWKS publication.

`kid` goes into every JWT header so a key rotation can publish two keys for
a transition window.
"""

from __future__ import annotations

from base64 import urlsafe_b64encode
from pathlib import Path

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import (
    RSAPrivateKey,
    RSAPublicKey,
    generate_private_key,
)
from joserfc.jwk import KeyParameters, RSAKey

from app.config import Settings


def _b64url_uint(n: int) -> str:
    """RFC 7518 base64url integer encoding for JWK n/e."""
    length = (n.bit_length() + 7) // 8
    return urlsafe_b64encode(n.to_bytes(length, "big")).rstrip(b"=").decode("ascii")


def _generate_dev_key() -> RSAPrivateKey:
    """Used only when ICS_DEBUG=1 and no key configured, never in prod
    (Settings refuses to start without an explicit key in non-debug mode)."""
    return generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())


# Manual cache: `lru_cache` would need Settings to be hashable, and the
# Pydantic Settings class isn't. Process-lifetime cache key = the PEM
# source (env value or path); both are short strings.
_KEY_CACHE: dict[str, RSAPrivateKey] = {}


def load_private_key(settings: Settings) -> RSAPrivateKey:
    cache_key = (
        f"pem:{settings.oauth_private_key_pem[:64]}"
        if settings.oauth_private_key_pem
        else f"path:{settings.oauth_private_key_pem_path}"
        if settings.oauth_private_key_pem_path
        else "__dev_generated__"
    )
    if cache_key in _KEY_CACHE:
        return _KEY_CACHE[cache_key]
    pem: bytes | None = None
    if settings.oauth_private_key_pem:
        pem = settings.oauth_private_key_pem.encode("utf-8")
    elif settings.oauth_private_key_pem_path:
        pem = Path(settings.oauth_private_key_pem_path).read_bytes()
    if pem is None:
        if not settings.debug:
            raise RuntimeError(
                "OAuth: neither ICS_OAUTH_PRIVATE_KEY_PEM nor _PATH is set. "
                "Generate a key with: openssl genrsa -out priv.pem 2048"
            )
        key = _generate_dev_key()
    else:
        loaded = serialization.load_pem_private_key(pem, password=None, backend=default_backend())
        if not isinstance(loaded, RSAPrivateKey):
            # RS256 needs an RSA key; anything else would only fail later,
            # on the first token signed.
            raise RuntimeError("OAuth: the configured private key is not an RSA key")
        key = loaded
    _KEY_CACHE[cache_key] = key
    return key


def public_key(settings: Settings) -> RSAPublicKey:
    return load_private_key(settings).public_key()


# joserfc keys, converted once per process. Keyed by (key, kid), not the key
# alone: several `Settings` can share one PEM (in debug all of them do), and
# the `kid` baked into the JWK must not leak from one configuration to another.
_JWK_CACHE: dict[tuple[RSAPrivateKey, str], tuple[RSAKey, RSAKey]] = {}


def _jwk_pair(settings: Settings) -> tuple[RSAKey, RSAKey]:
    private = load_private_key(settings)
    cache_key = (private, settings.oauth_kid)
    pair = _JWK_CACHE.get(cache_key)
    if pair is None:
        params: KeyParameters = {"kid": settings.oauth_kid}
        pair = (
            RSAKey.import_key(private, parameters=params),
            RSAKey.import_key(private.public_key(), parameters=params),
        )
        _JWK_CACHE[cache_key] = pair
    return pair


def signing_key(settings: Settings) -> RSAKey:
    """Private key for signing tokens (RS256)."""
    return _jwk_pair(settings)[0]


def verification_key(settings: Settings) -> RSAKey:
    """Public key for signature verification."""
    return _jwk_pair(settings)[1]


def public_jwk(settings: Settings) -> dict[str, str]:
    """Public key serialized as a JWK (RFC 7517) for /jwks.json."""
    pub = public_key(settings)
    numbers = pub.public_numbers()
    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": settings.oauth_kid,
        "n": _b64url_uint(numbers.n),
        "e": _b64url_uint(numbers.e),
    }


def jwks_document(settings: Settings) -> dict[str, list[dict[str, str]]]:
    return {"keys": [public_jwk(settings)]}
