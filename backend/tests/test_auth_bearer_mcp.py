"""Tests for MCP JWT validation in `app/auth.py` (Resource Server side).

Covers `_validate_bearer` and the Bearer dispatch in `get_current_user`. The
token is signed with `tokens_mod.sign_access_jwt` (process-cached dev RSA
keypair), then we hit the MCP-friendly endpoint `/api/auth/oauth/me`, whose
`Depends(get_current_user)` resolves the Bearer.

To avoid needing a real prod key and audience, we monkeypatch
`settings.mcp_resource_uri` and `oauth_kid` to test-only values; the key is
generated on the fly in `_generate_dev_key()` (debug mode is the default in
tests).
"""

from __future__ import annotations

import time

import pytest
from joserfc import jwt

from app.config import get_settings
from app.models import OAuthJTIBlacklist
from app.oauth import keys as keys_mod
from app.oauth import tokens as tokens_mod
from tests.conftest import login_as as _login
from tests.conftest import mk_user

_AUDIENCE = "https://ics-test.example/mcp"


def _enable_mcp(monkeypatch) -> None:
    """Enable audience-bound bearer validation. The key is generated in
    memory (debug mode). `oauth_issuer` must match the token."""
    s = get_settings()
    monkeypatch.setattr(s, "mcp_resource_uri", _AUDIENCE)
    monkeypatch.setattr(s, "debug", True)


def _make_jwt_for(user, *, audience: str = _AUDIENCE, jti: str | None = None) -> tuple[str, str]:
    """Returns (jwt_compact, jti), reusing the prod path boilerplate."""
    token, real_jti = tokens_mod.sign_access_jwt(
        settings=get_settings(),
        user=user,
        client_id_external="ics-mcp-stdio",
        scopes=["ics"],
        audience=audience,
        jti=jti,
    )
    return token, real_jti


# ---------- Happy path ----------


@pytest.mark.asyncio
async def test_bearer_grants_access_to_oauth_me(client, session, monkeypatch):
    _enable_mcp(monkeypatch)
    user = await mk_user(session)
    await session.commit()
    token, _jti = _make_jwt_for(user)

    r = await client.get(
        "/api/auth/oauth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == str(user.id)
    assert body["transport"] == "bearer"
    assert "ics" in body["scopes"]
    assert body["client_id"] == "ics-mcp-stdio"


# ---------- Error branches in _validate_bearer ----------


@pytest.mark.asyncio
async def test_bearer_with_missing_mcp_resource_uri_returns_500(client, session, monkeypatch):
    """Without `ICS_MCP_RESOURCE_URI` config the bearer cannot be verified;
    500 prevents silently accepting a token without audience binding."""
    s = get_settings()
    monkeypatch.setattr(s, "mcp_resource_uri", "")
    # Token signed with any audience: verify must fail on "no resource".
    r = await client.get(
        "/api/auth/oauth/me",
        headers={"Authorization": "Bearer garbage.token.value"},
    )
    assert r.status_code == 500


@pytest.mark.asyncio
async def test_bearer_with_garbage_token_returns_401(client, monkeypatch):
    _enable_mcp(monkeypatch)
    r = await client.get(
        "/api/auth/oauth/me",
        headers={"Authorization": "Bearer not.a.real.jwt"},
    )
    assert r.status_code == 401
    assert "WWW-Authenticate" in r.headers
    assert "Bearer" in r.headers["WWW-Authenticate"]


@pytest.mark.asyncio
async def test_bearer_with_wrong_audience_returns_401(client, session, monkeypatch):
    _enable_mcp(monkeypatch)
    user = await mk_user(session)
    await session.commit()
    token, _ = _make_jwt_for(user, audience="https://attacker.example/wrong-rs")

    r = await client.get(
        "/api/auth/oauth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_bearer_with_expired_token_returns_401(client, session, monkeypatch):
    """Sign a token with `exp` in the past (manual jwt.encode, bypassing
    `sign_access_jwt` to control the claims)."""
    _enable_mcp(monkeypatch)
    user = await mk_user(session)
    await session.commit()

    s = get_settings()
    issuer = s.oauth_issuer or s.base_url
    now = int(time.time())
    claims = {
        "iss": issuer,
        "sub": str(user.id),
        "aud": _AUDIENCE,
        "client_id": "ics-mcp-stdio",
        "scope": "ics",
        "jti": "expired-jti",
        "iat": now - 7200,
        "nbf": now - 7200,
        "exp": now - 3600,  # an hour ago
        "email": user.email,
        "email_verified": True,
    }
    header = {"alg": "RS256", "kid": s.oauth_kid, "typ": "JWT"}
    token = jwt.encode(header, claims, keys_mod.signing_key(s), algorithms=["RS256"])

    r = await client.get(
        "/api/auth/oauth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_bearer_with_revoked_jti_returns_401(client, session, monkeypatch):
    """JTI on the blacklist: the token is cryptographically valid but revoked."""
    _enable_mcp(monkeypatch)
    user = await mk_user(session)
    token, jti = _make_jwt_for(user)
    from datetime import UTC, datetime, timedelta

    session.add(
        OAuthJTIBlacklist(
            jti=jti,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    await session.commit()

    r = await client.get(
        "/api/auth/oauth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 401
    assert "revoked" in r.json()["detail"]


@pytest.mark.asyncio
async def test_bearer_with_deleted_user_returns_401(client, session, monkeypatch):
    _enable_mcp(monkeypatch)
    user = await mk_user(session)
    await session.commit()
    token, _ = _make_jwt_for(user)

    await session.delete(user)
    await session.commit()

    r = await client.get(
        "/api/auth/oauth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 401
    assert "user not found" in r.json()["detail"]


@pytest.mark.asyncio
async def test_bearer_with_locked_user_returns_403(client, session, monkeypatch):
    from datetime import UTC, datetime, timedelta

    _enable_mcp(monkeypatch)
    user = await mk_user(session)
    user.locked_until = datetime.now(UTC) + timedelta(hours=1)
    await session.commit()
    token, _ = _make_jwt_for(user)

    r = await client.get(
        "/api/auth/oauth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403
    assert "locked" in r.json()["detail"]


# ---------- Dispatch in get_current_user ----------


@pytest.mark.asyncio
async def test_bearer_with_empty_header_falls_back_to_cookie(client, session, monkeypatch):
    """Authorization: Bearer (alone): `_bearer_token` returns None, dispatch
    falls through to the session cookie. No session -> 401."""
    _enable_mcp(monkeypatch)
    r = await client.get("/api/auth/oauth/me", headers={"Authorization": "Bearer "})
    assert r.status_code == 401
    # No "invalid_token: " means the dispatch took the cookie path
    assert "invalid_token" not in r.json()["detail"]


@pytest.mark.asyncio
async def test_cookie_session_with_deleted_user_returns_401(client, session, monkeypatch):
    """Cookie kept after the user was deleted (e.g. account removed on offboarding)."""
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    # /me works via cookie
    r1 = await client.get("/api/auth/oauth/me")
    assert r1.status_code == 200

    # Delete the user, the cookie stays
    await session.delete(user)
    await session.commit()

    r2 = await client.get("/api/auth/oauth/me")
    assert r2.status_code == 401


@pytest.mark.asyncio
async def test_dev_stub_sso_creates_user_with_xdev_header(client, session, monkeypatch):
    """`ICS_DEV_STUB_SSO=1`: `X-Dev-User: <email>` creates/returns the user.
    Used by the frontend dev stack without real OIDC."""
    s = get_settings()
    monkeypatch.setattr(s, "dev_stub_sso", True)

    from app.slug import generate_slug

    email = f"ephemeral+{generate_slug(6)}@example.com"
    r = await client.get(
        "/api/auth/oauth/me",
        headers={"X-Dev-User": email},
    )
    assert r.status_code == 200
    assert r.json()["email"] == email
    assert r.json()["transport"] == "dev_stub"


@pytest.mark.asyncio
async def test_dev_stub_sso_rejects_unallowed_domain(client, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "dev_stub_sso", True)

    r = await client.get(
        "/api/auth/oauth/me",
        headers={"X-Dev-User": "attacker@malicious.example"},
    )
    assert r.status_code == 403
