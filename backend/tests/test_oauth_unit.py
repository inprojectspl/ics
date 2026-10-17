"""Unit tests for OAuth crypto primitives: keys, state, PKCE.

These don't need a DB or a running Redis; they're pure Python checks
of the security-critical building blocks.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from base64 import urlsafe_b64encode

import pytest

from app.config import Settings
from app.oauth import keys, scopes, state, tokens


@pytest.fixture
def settings_dev() -> Settings:
    return Settings(debug=True, secret_key="unit-test-secret-key-32-bytes-min")


def test_pkce_s256_roundtrip(settings_dev):
    # Verify our PKCE check matches RFC 7636 §4.6
    from app.oauth.server import _verify_pkce

    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    assert _verify_pkce(verifier, challenge) is True
    assert _verify_pkce(verifier + "x", challenge) is False
    assert _verify_pkce(verifier, challenge + "x") is False


def test_state_signed_token_roundtrip(settings_dev):
    token = state.issue(settings_dev, {"foo": "bar", "n": 1})
    payload = state.verify(settings_dev, token)
    assert payload is not None
    assert payload["foo"] == "bar"
    assert payload["n"] == 1


def test_state_tampered_token_rejected(settings_dev):
    token = state.issue(settings_dev, {"foo": "bar"})
    body, sig = token.rsplit(".", 1)
    # Replace the entire sig with a same-length random nonce: no chance of
    # accidentally producing a valid signature.
    bogus = secrets.token_urlsafe(len(sig))[: len(sig)]
    assert state.verify(settings_dev, f"{body}.{bogus}") is None
    # Also flip a meaningful payload byte and ensure rejection:
    bad_body = body[:-2] + ("AA" if not body.endswith("AA") else "BB")
    assert state.verify(settings_dev, f"{bad_body}.{sig}") is None


def test_state_wrong_secret_rejected(settings_dev):
    token = state.issue(settings_dev, {"foo": "bar"})
    other = Settings(debug=True, secret_key="totally-different-secret-32-bytes")
    assert state.verify(other, token) is None


def test_jwks_document_has_required_fields(settings_dev):
    doc = keys.jwks_document(settings_dev)
    assert "keys" in doc and len(doc["keys"]) == 1
    jwk = doc["keys"][0]
    for field in ("kty", "use", "alg", "kid", "n", "e"):
        assert field in jwk, f"missing JWK field: {field}"
    assert jwk["kty"] == "RSA"
    assert jwk["alg"] == "RS256"


def test_signing_key_carries_the_kid_of_its_own_settings():
    """Two configurations share a private key (generated once in debug), but
    each has its own `kid` and must get it in its JWK. A cache keyed only by
    the private key would hand the first `kid` to the second."""
    a = Settings(debug=True, secret_key="unit-test-secret-key-32-bytes-min", oauth_kid="kid-a")
    b = Settings(debug=True, secret_key="unit-test-secret-key-32-bytes-min", oauth_kid="kid-b")

    assert keys.signing_key(a).kid == "kid-a"
    assert keys.verification_key(a).kid == "kid-a"
    assert keys.signing_key(b).kid == "kid-b"
    assert keys.verification_key(b).kid == "kid-b"


def test_jwt_sign_and_verify_audience_bound(settings_dev):
    from datetime import UTC, datetime

    from app.models import User

    settings_dev.mcp_resource_uri = "https://ics.test/mcp"
    settings_dev.base_url = "https://ics.test"
    u = User(
        email="alice@example.com",
        display_name="Alice",
        role="user",
        email_verified_at=datetime.now(UTC),
    )
    # Hack: set a deterministic id (avoid full DB roundtrip in this unit test)
    from uuid import UUID

    u.id = UUID("12345678-1234-5678-1234-567812345678")
    token, jti = tokens.sign_access_jwt(
        settings=settings_dev,
        user=u,
        client_id_external="ics-mcp-stdio",
        scopes=["ics"],
        audience="https://ics.test/mcp",
    )
    claims = tokens.verify_access_jwt(settings_dev, token, expected_audience="https://ics.test/mcp")
    assert claims["sub"] == str(u.id)
    assert claims["aud"] == "https://ics.test/mcp"
    assert claims["jti"] == jti
    assert claims["scope"] == "ics"
    assert claims["client_id"] == "ics-mcp-stdio"


def test_jwt_audience_mismatch_rejected(settings_dev):
    from uuid import UUID

    from joserfc.errors import InvalidClaimError

    from app.models import User

    settings_dev.mcp_resource_uri = "https://ics.test/mcp"
    settings_dev.base_url = "https://ics.test"
    u = User(email="bob@example.com", display_name="Bob", role="user")
    u.id = UUID("11111111-2222-3333-4444-555555555555")
    token, _jti = tokens.sign_access_jwt(
        settings=settings_dev,
        user=u,
        client_id_external="ics-mcp-stdio",
        scopes=["ics"],
        audience="https://ics.test/mcp",
    )
    with pytest.raises(InvalidClaimError):
        tokens.verify_access_jwt(settings_dev, token, expected_audience="https://OTHER/mcp")


def test_jwt_signed_with_a_symmetric_key_is_rejected(settings_dev):
    """The signature must be RS256 with our key and nothing else.

    A classic attack on JWT verifiers swaps the `alg` header for a symmetric
    algorithm and signs the token with material the verifier exposes anyway
    (for us, the public key from JWKS). Passing the algorithm list explicitly
    when decoding closes that path.
    """
    from joserfc import jwt as raw_jwt
    from joserfc.errors import JoseError
    from joserfc.jwk import OctKey

    settings_dev.base_url = "https://ics.test"
    now = int(time.time())
    forged = raw_jwt.encode(
        {"alg": "HS256", "kid": settings_dev.oauth_kid, "typ": "JWT"},
        {
            "iss": "https://ics.test",
            "sub": "11111111-2222-3333-4444-555555555555",
            "aud": "https://ics.test/mcp",
            "jti": "forged",
            "iat": now,
            "exp": now + 3600,
        },
        OctKey.import_key("irrelevant-secret"),
        algorithms=["HS256"],
    )
    with pytest.raises(JoseError):
        tokens.verify_access_jwt(settings_dev, forged, expected_audience="https://ics.test/mcp")


def test_jwt_signed_with_a_foreign_rsa_key_is_rejected(settings_dev):
    """A token signed with someone else's RSA key fails verification."""
    from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key
    from joserfc import jwt as raw_jwt
    from joserfc.errors import JoseError
    from joserfc.jwk import RSAKey

    settings_dev.base_url = "https://ics.test"
    now = int(time.time())
    intruder = RSAKey.import_key(generate_private_key(public_exponent=65537, key_size=2048))
    forged = raw_jwt.encode(
        {"alg": "RS256", "kid": settings_dev.oauth_kid, "typ": "JWT"},
        {
            "iss": "https://ics.test",
            "sub": "11111111-2222-3333-4444-555555555555",
            "aud": "https://ics.test/mcp",
            "jti": "forged",
            "iat": now,
            "exp": now + 3600,
        },
        intruder,
        algorithms=["RS256"],
    )
    with pytest.raises(JoseError):
        tokens.verify_access_jwt(settings_dev, forged, expected_audience="https://ics.test/mcp")


def test_scopes_validate_intersects():
    assert scopes.validate_scopes(["ics", "weird"], ["ics"]) == ["ics"]
    assert scopes.validate_scopes(["weird"], ["ics"]) == []
    assert scopes.normalize_scope_string("ics  read") == ["ics", "read"]
