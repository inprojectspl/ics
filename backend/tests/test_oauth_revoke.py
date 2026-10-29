"""Tests for `oauth/server/revoke.py`: RFC 7009 token revocation."""

from __future__ import annotations

import pytest

from tests.conftest import login_as as _login
from tests.conftest import mk_user


@pytest.mark.asyncio
async def test_revoke_without_token_returns_400(client):
    r = await client.post("/api/auth/oauth/revoke", data={})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_revoke_token_sent_as_file_returns_400(client):
    r = await client.post("/api/auth/oauth/revoke", files={"token": ("t.txt", b"abc")})
    assert r.status_code == 400
    assert r.json()["code"] == "invalid_request"


@pytest.mark.asyncio
async def test_revoke_refresh_token_with_hint_succeeds(client, session):
    """RFC 7009: hint=refresh_token + valid token -> 200 + record revoked."""
    from tests.conftest import full_oauth_flow, register_oauth_client

    dcr = await register_oauth_client(client, name="Rev Test")
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    body = await full_oauth_flow(client, dcr["client_id"])
    refresh = body["refresh_token"]

    rev = await client.post(
        "/api/auth/oauth/revoke",
        data={"token": refresh, "token_type_hint": "refresh_token"},
    )
    assert rev.status_code == 200

    # Reusing a revoked refresh token -> 400
    reuse = await client.post(
        "/api/auth/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": dcr["client_id"],
        },
    )
    assert reuse.status_code == 400


async def _connected(client, session, monkeypatch) -> tuple[dict, dict]:
    from app.config import get_settings
    from tests.conftest import full_oauth_flow, signed_in_oauth_client

    # Bearer authentication needs a resource URI; the default test settings have none.
    monkeypatch.setattr(get_settings(), "mcp_resource_uri", "https://ics-test.example/mcp")
    dcr = await signed_in_oauth_client(client, session)
    return dcr, await full_oauth_flow(client, dcr["client_id"])


async def _me(client, access_token: str) -> int:
    r = await client.get("/api/auth/oauth/me", headers={"Authorization": f"Bearer {access_token}"})
    return r.status_code


@pytest.mark.asyncio
@pytest.mark.parametrize("hint", [None, "access_token", "refresh_token"])
async def test_revoking_a_refresh_token_ends_the_grant_whatever_the_hint(
    client, session, monkeypatch, hint
):
    """RFC 7009: the hint is optional and may be wrong. The refresh token stops
    working and so does the access token issued with it."""
    dcr, body = await _connected(client, session, monkeypatch)
    assert await _me(client, body["access_token"]) == 200

    data = {"token": body["refresh_token"]}
    if hint:
        data["token_type_hint"] = hint
    assert (await client.post("/api/auth/oauth/revoke", data=data)).status_code == 200

    refresh = await client.post(
        "/api/auth/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": body["refresh_token"],
            "client_id": dcr["client_id"],
        },
    )
    assert refresh.status_code == 400
    assert await _me(client, body["access_token"]) == 401


@pytest.mark.asyncio
async def test_refresh_reuse_also_cuts_the_newest_access_token(client, session, monkeypatch):
    dcr, first = await _connected(client, session, monkeypatch)
    grant = {"grant_type": "refresh_token", "client_id": dcr["client_id"]}
    rotated = await client.post(
        "/api/auth/oauth/token", data={**grant, "refresh_token": first["refresh_token"]}
    )
    assert rotated.status_code == 200
    newest = rotated.json()["access_token"]
    assert await _me(client, newest) == 200

    reuse = await client.post(
        "/api/auth/oauth/token", data={**grant, "refresh_token": first["refresh_token"]}
    )
    assert reuse.status_code == 400
    assert await _me(client, newest) == 401


@pytest.mark.asyncio
async def test_revoke_access_jwt_blacklists_jti(client, session, monkeypatch):
    """POST /revoke with an access JWT -> JTI blacklisted, /me with that token -> 401."""
    from app.config import get_settings
    from app.oauth import tokens as tokens_mod

    s = get_settings()
    monkeypatch.setattr(s, "mcp_resource_uri", "https://ics-test.example/mcp")
    monkeypatch.setattr(s, "debug", True)

    user = await mk_user(session)
    await session.commit()
    access_jwt, _jti = tokens_mod.sign_access_jwt(
        settings=s,
        user=user,
        client_id_external="ics-mcp-stdio",
        scopes=["ics"],
        audience="https://ics-test.example/mcp",
    )

    rev = await client.post(
        "/api/auth/oauth/revoke",
        data={"token": access_jwt},
    )
    assert rev.status_code == 200

    # The token is blacklisted: /me with this JWT -> 401 token_revoked.
    me = await client.get(
        "/api/auth/oauth/me",
        headers={"Authorization": f"Bearer {access_jwt}"},
    )
    assert me.status_code == 401
    assert "revoked" in me.json()["detail"]


@pytest.mark.asyncio
async def test_revoke_garbage_token_returns_200(client):
    """RFC 7009 §2.2: an invalid token value -> 200 (no info leak)."""
    r = await client.post(
        "/api/auth/oauth/revoke",
        data={"token": "definitely-not-a-real-jwt"},
    )
    assert r.status_code == 200


def _signed_access_jwt(monkeypatch, user) -> str:
    from app.config import get_settings
    from app.oauth import tokens as tokens_mod

    s = get_settings()
    monkeypatch.setattr(s, "mcp_resource_uri", "https://ics-test.example/mcp")
    token, _jti = tokens_mod.sign_access_jwt(
        settings=s,
        user=user,
        client_id_external="ics-mcp-stdio",
        scopes=["ics"],
        audience="https://ics-test.example/mcp",
    )
    return token


@pytest.mark.asyncio
async def test_revoke_commit_failure_is_a_server_error(session, monkeypatch):
    """A failed blacklist write must not answer 200: the client would drop a
    token that is still valid. Only bad tokens get the RFC 7009 silent 200."""
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.exc import OperationalError

    from app.db import get_session
    from app.main import create_app

    user = await mk_user(session)
    await session.commit()
    token = _signed_access_jwt(monkeypatch, user)

    async def failing_commit():
        raise OperationalError("COMMIT", {}, Exception("connection lost"))

    app = create_app()

    async def _override_session():
        yield session

    app.dependency_overrides[get_session] = _override_session
    monkeypatch.setattr(session, "commit", failing_commit)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        r = await ac.post("/api/auth/oauth/revoke", data={"token": token})
    assert r.status_code == 500


@pytest.mark.asyncio
async def test_revoke_access_jwt_twice_is_idempotent(client, session, monkeypatch):
    user = await mk_user(session)
    await session.commit()
    token = _signed_access_jwt(monkeypatch, user)
    for _ in range(2):
        r = await client.post("/api/auth/oauth/revoke", data={"token": token})
        assert r.status_code == 200
