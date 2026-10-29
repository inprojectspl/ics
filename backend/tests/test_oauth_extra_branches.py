"""Missing branches in `oauth/server/{token,authorize}.py`.

Complements test_oauth_flow.py, which already covers the happy path and most
edge cases. This file covers what is not on the 'user logged in -> consent ->
exchange' path:
- replay of a spent authcode (used_at), expired authcode, wrong redirect_uri
  on /token, resource mismatch code vs token, user deleted after consent
- /authorize refusals: response_type != code, short code_challenge,
  invalid_target/audience, invalid_scope
- POST /authorize with a different user's session than the one in the state token
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select

from app.models import OAuthAuthCode, OAuthClient
from app.oauth import tokens as tokens_mod
from tests.conftest import (
    STATE_TOKEN_RE,
    mk_user,
    register_oauth_client,
)
from tests.conftest import (
    do_authorize_get_code as _do_authorize_and_get_code,
)
from tests.conftest import (
    login_as as _login,
)
from tests.conftest import (
    make_pkce as _make_pkce,
)
from tests.conftest import (
    resource_uri as _resource,
)


async def _register_client(client):
    return await register_oauth_client(client, name="Edge Test")


# ---------- /token: replay + edge cases ----------


@pytest.mark.asyncio
async def test_token_rejects_replay_of_used_authcode(client, session):
    """After the first successful exchange the code is marked `used_at`;
    a second call must return 400 invalid_grant (replay protection)."""
    dcr = await _register_client(client)
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    code_verifier, code_challenge = _make_pkce()
    code = await _do_authorize_and_get_code(client, dcr["client_id"], code_challenge)

    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": "http://localhost:9000/callback",
        "code_verifier": code_verifier,
        "client_id": dcr["client_id"],
        "resource": _resource(),
    }
    r1 = await client.post("/api/auth/oauth/token", data=payload)
    assert r1.status_code == 200

    r2 = await client.post("/api/auth/oauth/token", data=payload)
    assert r2.status_code == 400


@pytest.mark.asyncio
async def test_token_rejects_expired_authcode(client, session):
    """Backdate `expires_at` directly in the DB to simulate exceeding
    `oauth_authcode_ttl`."""
    dcr = await _register_client(client)
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    code_verifier, code_challenge = _make_pkce()
    code = await _do_authorize_and_get_code(client, dcr["client_id"], code_challenge)

    code_hash = tokens_mod.hash_token(code)
    row = await session.scalar(select(OAuthAuthCode).where(OAuthAuthCode.code_hash == code_hash))
    row.expires_at = datetime.now(UTC) - timedelta(seconds=5)
    await session.commit()

    r = await client.post(
        "/api/auth/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "http://localhost:9000/callback",
            "code_verifier": code_verifier,
            "client_id": dcr["client_id"],
            "resource": _resource(),
        },
    )
    assert r.status_code == 400
    assert "expired" in r.json()["detail"]


@pytest.mark.asyncio
async def test_token_rejects_redirect_uri_mismatch(client, session):
    """The client sends a different `redirect_uri` to /token than it used in /authorize."""
    dcr = await _register_client(client)
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    code_verifier, code_challenge = _make_pkce()
    code = await _do_authorize_and_get_code(client, dcr["client_id"], code_challenge)

    r = await client.post(
        "/api/auth/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "http://localhost:9000/different-callback",
            "code_verifier": code_verifier,
            "client_id": dcr["client_id"],
            "resource": _resource(),
        },
    )
    assert r.status_code == 400
    assert "redirect_uri" in r.json()["detail"]


@pytest.mark.asyncio
async def test_token_rejects_resource_mismatch_on_code_exchange(client, session):
    """RFC 8707: `resource` on /token must be === the resource from /authorize."""
    dcr = await _register_client(client)
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    code_verifier, code_challenge = _make_pkce()
    code = await _do_authorize_and_get_code(client, dcr["client_id"], code_challenge)

    r = await client.post(
        "/api/auth/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "http://localhost:9000/callback",
            "code_verifier": code_verifier,
            "client_id": dcr["client_id"],
            "resource": "https://attacker.example/wrong-audience",
        },
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_token_rejects_unknown_client_id_on_exchange(client, session):
    """Code issued for DCR client A, exchanged with client_id=B."""
    dcr_a = await _register_client(client)
    dcr_b_resp = await client.post(
        "/api/auth/oauth/register",
        json={"client_name": "B", "redirect_uris": ["http://localhost:9000/callback"]},
    )
    dcr_b = dcr_b_resp.json()
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    code_verifier, code_challenge = _make_pkce()
    code = await _do_authorize_and_get_code(client, dcr_a["client_id"], code_challenge)

    r = await client.post(
        "/api/auth/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "http://localhost:9000/callback",
            "code_verifier": code_verifier,
            "client_id": dcr_b["client_id"],  # different client
            "resource": _resource(),
        },
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_token_missing_required_fields_returns_400(client):
    """Missing `code` / `client_id` / `redirect_uri` -> 400 invalid_request."""
    r = await client.post(
        "/api/auth/oauth/token",
        data={"grant_type": "authorization_code"},
    )
    assert r.status_code == 400


# ---------- /authorize: missing branches ----------


@pytest.mark.asyncio
async def test_authorize_rejects_non_code_response_type(client, session):
    dcr = await _register_client(client)
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    _, code_challenge = _make_pkce()
    r = await client.get(
        "/api/auth/oauth/authorize",
        params={
            "response_type": "token",  # implicit grant, forbidden in OAuth 2.1
            "client_id": dcr["client_id"],
            "redirect_uri": "http://localhost:9000/callback",
            "scope": "ics",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "resource": _resource(),
        },
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_authorize_rejects_short_code_challenge(client, session):
    dcr = await _register_client(client)
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    r = await client.get(
        "/api/auth/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": dcr["client_id"],
            "redirect_uri": "http://localhost:9000/callback",
            "scope": "ics",
            "code_challenge": "short",  # < 43 chars
            "code_challenge_method": "S256",
            "resource": _resource(),
        },
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_authorize_rejects_disallowed_audience(client, session):
    dcr = await _register_client(client)
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    _, code_challenge = _make_pkce()
    r = await client.get(
        "/api/auth/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": dcr["client_id"],
            "redirect_uri": "http://localhost:9000/callback",
            "scope": "ics",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "resource": "https://other-rs.example/api",
        },
    )
    assert r.status_code == 400
    assert "resource" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_authorize_rejects_invalid_scope(client, session):
    dcr = await _register_client(client)
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    _, code_challenge = _make_pkce()
    r = await client.get(
        "/api/auth/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": dcr["client_id"],
            "redirect_uri": "http://localhost:9000/callback",
            "scope": "definitely-not-a-real-scope",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "resource": _resource(),
        },
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_authorize_redirects_anonymous_to_login(client):
    """Without a session `/authorize` redirects to the frontend login with `next=`."""
    r = await client.get(
        "/api/auth/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": "some-client",
            "redirect_uri": "http://localhost:9000/callback",
            "scope": "ics",
            "code_challenge": "x" * 43,
            "code_challenge_method": "S256",
            "resource": _resource(),
        },
        follow_redirects=False,
    )
    assert r.status_code in (302, 307)
    route, _, query = urlsplit(r.headers["location"]).fragment.partition("?")
    assert route == "login"
    original = urlsplit(str(r.request.url))
    assert parse_qs(query) == {"next": [f"{original.path}?{original.query}"]}


@pytest.mark.asyncio
async def test_post_authorize_session_user_mismatch_returns_403(client, session):
    """User A logs in and does GET /authorize (gets a state_token for User A).
    Then User A logs out and User B logs in. A POST with A's state_token
    must return 403 (cross-account hijack)."""
    dcr = await _register_client(client)
    user_a = await mk_user(session)
    user_b = await mk_user(session)
    await session.commit()
    await _login(client, user_a)

    _, code_challenge = _make_pkce()
    r = await client.get(
        "/api/auth/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": dcr["client_id"],
            "redirect_uri": "http://localhost:9000/callback",
            "scope": "ics",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "resource": _resource(),
        },
    )
    state_token = STATE_TOKEN_RE.search(r.text).group(1)

    # User A -> log out, User B -> log in
    await client.post("/api/auth/logout")
    await _login(client, user_b)

    r2 = await client.post(
        "/api/auth/oauth/authorize",
        data={"state_token": state_token, "decision": "allow"},
        follow_redirects=False,
    )
    assert r2.status_code == 403


@pytest.mark.asyncio
async def test_post_authorize_rejects_after_client_revoked(client, session):
    """The client was revoked between GET and POST consent -> 400."""
    dcr = await _register_client(client)
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    _, code_challenge = _make_pkce()
    r = await client.get(
        "/api/auth/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": dcr["client_id"],
            "redirect_uri": "http://localhost:9000/callback",
            "scope": "ics",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "resource": _resource(),
        },
    )
    state_token = STATE_TOKEN_RE.search(r.text).group(1)

    # Revoke between GET and POST.
    db_client = await session.scalar(
        select(OAuthClient).where(OAuthClient.client_id == dcr["client_id"])
    )
    db_client.revoked_at = datetime.now(UTC)
    await session.commit()

    r2 = await client.post(
        "/api/auth/oauth/authorize",
        data={"state_token": state_token, "decision": "allow"},
        follow_redirects=False,
    )
    assert r2.status_code == 400


# ---------- refresh: small missing cases ----------


@pytest.mark.asyncio
async def test_refresh_rejects_missing_token_field(client):
    """`grant_type=refresh_token` but no `refresh_token` in the body."""
    r = await client.post(
        "/api/auth/oauth/token",
        data={"grant_type": "refresh_token"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_refresh_rejects_client_id_mismatch(client, session):
    """Refresh token issued for DCR client A, used with `client_id=B`."""
    dcr_a = await _register_client(client)
    dcr_b = await register_oauth_client(client, name="B2")
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    code_verifier, code_challenge = _make_pkce()
    code = await _do_authorize_and_get_code(client, dcr_a["client_id"], code_challenge)

    r = await client.post(
        "/api/auth/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "http://localhost:9000/callback",
            "code_verifier": code_verifier,
            "client_id": dcr_a["client_id"],
            "resource": _resource(),
        },
    )
    refresh = r.json()["refresh_token"]

    r2 = await client.post(
        "/api/auth/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": dcr_b["client_id"],  # wrong client
        },
    )
    assert r2.status_code == 400


@pytest.mark.asyncio
async def test_authorize_get_session_with_deleted_user_returns_401(client, session):
    """The session cookie points at a user id that no longer exists in the DB.
    Attack of the 'deleted user, session persists in Redis' kind -> 401."""
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    await session.delete(user)
    await session.commit()

    _, code_challenge = _make_pkce()
    r = await client.get(
        "/api/auth/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": "anything",
            "redirect_uri": "http://localhost:9000/callback",
            "scope": "ics",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "resource": _resource(),
        },
        follow_redirects=False,
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_authcode_with_deleted_user_returns_400(client, session):
    """User existed at consent, deleted before exchange -> invalid_grant."""
    from app.models import User

    dcr = await _register_client(client)
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    code_verifier, code_challenge = _make_pkce()
    code = await _do_authorize_and_get_code(client, dcr["client_id"], code_challenge)

    user_db = await session.get(User, user.id)
    await session.delete(user_db)
    await session.commit()

    r = await client.post(
        "/api/auth/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "http://localhost:9000/callback",
            "code_verifier": code_verifier,
            "client_id": dcr["client_id"],
            "resource": _resource(),
        },
    )
    assert r.status_code == 400


# ---------- POST /authorize: missing state cases ----------


@pytest.mark.asyncio
async def test_post_authorize_without_session_returns_403(client):
    """POST consent without an ICS session -> 403 (state mismatch: current_user_id is None)."""
    # The state_token does not exist, so this is 403 invalid_state_token.
    r = await client.post(
        "/api/auth/oauth/authorize",
        data={"state_token": "garbage.token.value", "decision": "allow"},
        follow_redirects=False,
    )
    assert r.status_code == 403
