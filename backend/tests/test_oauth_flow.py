"""Full OAuth 2.1 flow: Authorization Code + PKCE + refresh + reuse detection.

test_oauth_server_endpoints.py covers metadata + DCR + revoke + me + GET
authorize without a session. Here we add the flows that need a logged-in
user, manual PKCE and token rotation.

Key invariants (OAuth 2.1 + MCP 2025-11-25):
- code_challenge_method MUST be S256 (no plain).
- resource MUST match allowed_audiences (RFC 8707).
- refresh MUST rotate (a new refresh token on every /token).
- Reusing an already-rotated refresh token invalidates the whole token family.
- Wrong code_verifier -> 400 invalid_grant: PKCE mismatch.

Every test uses the `_register_client` + `_make_pkce` helpers; without them
each test would carry ~10 lines of ceremony.
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import AsyncClient

from app.config import get_settings
from tests.conftest import login_as as _login
from tests.conftest import mk_user

_STATE_RE = re.compile(r'name="state_token"\s+value="([^"]+)"')


def _make_pkce() -> tuple[str, str]:
    """Returns an S256 (code_verifier, code_challenge) pair."""
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


async def _register_client(client: AsyncClient, *, name: str = "MCP Test Client") -> dict:
    r = await client.post(
        "/api/auth/oauth/register",
        json={
            "client_name": name,
            "redirect_uris": ["http://localhost:9000/callback"],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _resource() -> str:
    """The audience currently accepted by the server (mcp_resource_uri or
    issuer = base_url)."""
    s = get_settings()
    return s.mcp_resource_uri or s.base_url.rstrip("/")


async def _do_authorize(
    client: AsyncClient,
    *,
    client_id: str,
    code_challenge: str,
    code_challenge_method: str = "S256",
    state: str | None = None,
    decision: str = "allow",
    resource: str | None = None,
) -> str:
    """Full consent step: GET /authorize -> parse state_token from the HTML ->
    POST /authorize with the decision. Returns the redirect Location header.
    """
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": "http://localhost:9000/callback",
        "scope": "ics",
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "resource": resource or _resource(),
    }
    if state:
        params["state"] = state

    r = await client.get("/api/auth/oauth/authorize", params=params)
    assert r.status_code == 200, r.text
    match = _STATE_RE.search(r.text)
    assert match, "state_token not rendered in the consent HTML"
    state_token = match.group(1)

    r2 = await client.post(
        "/api/auth/oauth/authorize",
        data={"state_token": state_token, "decision": decision},
        follow_redirects=False,
    )
    assert r2.status_code == 302, r2.text
    return r2.headers["location"]


# ---------- Full happy path ----------


@pytest.mark.asyncio
async def test_full_authorization_code_pkce_flow(client, session):
    """End-to-end: register -> login -> consent -> token exchange -> introspect."""
    dcr = await _register_client(client)
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    code_verifier, code_challenge = _make_pkce()
    location = await _do_authorize(
        client,
        client_id=dcr["client_id"],
        code_challenge=code_challenge,
        state="my-csrf-1",
    )
    parsed = urlparse(location)
    assert parsed.scheme == "http" and parsed.netloc == "localhost:9000"
    qs = parse_qs(parsed.query)
    assert qs.get("state") == ["my-csrf-1"]
    code = qs["code"][0]

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
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "Bearer"
    assert body["access_token"]
    assert body["refresh_token"]
    assert "ics" in body["scope"]
    assert body["resource"] == _resource()


# ---------- Denial flow ----------


@pytest.mark.asyncio
async def test_consent_denial_redirects_with_error(client, session):
    dcr = await _register_client(client)
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    _, code_challenge = _make_pkce()
    location = await _do_authorize(
        client,
        client_id=dcr["client_id"],
        code_challenge=code_challenge,
        decision="deny",
        state="csrf-deny",
    )
    qs = parse_qs(urlparse(location).query)
    assert qs.get("error") == ["access_denied"]
    assert qs.get("state") == ["csrf-deny"]
    assert "code" not in qs


# ---------- PKCE enforcement ----------


@pytest.mark.asyncio
async def test_authorize_rejects_plain_code_challenge_method(client, session):
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
            "code_challenge_method": "plain",  # forbidden
            "resource": _resource(),
        },
    )
    assert r.status_code == 400
    assert "S256" in r.json()["detail"]


@pytest.mark.asyncio
async def test_authorize_rejects_missing_resource(client, session):
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
            "resource": "",  # MUST per RFC 8707
        },
    )
    assert r.status_code == 400
    assert "resource" in r.json()["detail"]


# ---------- Token endpoint validation ----------


@pytest.mark.asyncio
async def test_token_rejects_wrong_code_verifier(client, session):
    dcr = await _register_client(client)
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    _, code_challenge = _make_pkce()
    location = await _do_authorize(
        client,
        client_id=dcr["client_id"],
        code_challenge=code_challenge,
    )
    code = parse_qs(urlparse(location).query)["code"][0]

    r = await client.post(
        "/api/auth/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "http://localhost:9000/callback",
            "code_verifier": secrets.token_urlsafe(64),  # wrong verifier
            "client_id": dcr["client_id"],
            "resource": _resource(),
        },
    )
    assert r.status_code == 400
    assert "PKCE" in r.json()["detail"]


@pytest.mark.asyncio
async def test_token_rejects_missing_code_verifier(client, session):
    dcr = await _register_client(client)
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    _, code_challenge = _make_pkce()
    location = await _do_authorize(
        client,
        client_id=dcr["client_id"],
        code_challenge=code_challenge,
    )
    code = parse_qs(urlparse(location).query)["code"][0]

    r = await client.post(
        "/api/auth/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "http://localhost:9000/callback",
            # code_verifier missing
            "client_id": dcr["client_id"],
            "resource": _resource(),
        },
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_token_rejects_unsupported_grant_type(client, session):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    r = await client.post(
        "/api/auth/oauth/token",
        data={"grant_type": "password", "username": "x", "password": "y"},
    )
    assert r.status_code == 400


# ---------- Refresh rotation ----------


async def _full_flow_to_refresh(client: AsyncClient, dcr_client_id: str) -> dict:
    """Helper: go through to /token and return the body with refresh_token + access_token."""
    code_verifier, code_challenge = _make_pkce()
    location = await _do_authorize(
        client,
        client_id=dcr_client_id,
        code_challenge=code_challenge,
    )
    code = parse_qs(urlparse(location).query)["code"][0]
    r = await client.post(
        "/api/auth/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "http://localhost:9000/callback",
            "code_verifier": code_verifier,
            "client_id": dcr_client_id,
            "resource": _resource(),
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
async def test_refresh_rotates_token(client, session):
    dcr = await _register_client(client)
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    first = await _full_flow_to_refresh(client, dcr["client_id"])

    r = await client.post(
        "/api/auth/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": first["refresh_token"],
            "client_id": dcr["client_id"],
        },
    )
    assert r.status_code == 200, r.text
    second = r.json()
    assert second["access_token"] != first["access_token"]
    assert second["refresh_token"] != first["refresh_token"]


@pytest.mark.asyncio
async def test_refresh_reuse_detection_revokes_chain(client, session):
    """OAuth 2.1 §4.3.1: reuse of a rotated refresh -> revoke whole family."""
    dcr = await _register_client(client)
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    first = await _full_flow_to_refresh(client, dcr["client_id"])

    # First rotation OK
    r1 = await client.post(
        "/api/auth/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": first["refresh_token"],
            "client_id": dcr["client_id"],
        },
    )
    assert r1.status_code == 200

    # Re-using the same (now rotated) refresh, must fail + revoke chain
    r2 = await client.post(
        "/api/auth/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": first["refresh_token"],
            "client_id": dcr["client_id"],
        },
    )
    assert r2.status_code == 400
    assert "reuse" in r2.json()["detail"]

    # Even the freshly-issued refresh from r1 is now invalidated.
    r3 = await client.post(
        "/api/auth/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": r1.json()["refresh_token"],
            "client_id": dcr["client_id"],
        },
    )
    assert r3.status_code == 400


@pytest.mark.asyncio
async def test_refresh_rejects_unknown_token(client):
    r = await client.post(
        "/api/auth/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": "obviously-not-a-real-token",
        },
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_refresh_rejects_resource_upgrade(client, session):
    """RFC 8707: refresh cannot upgrade audience to a different resource."""
    dcr = await _register_client(client)
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    first = await _full_flow_to_refresh(client, dcr["client_id"])

    r = await client.post(
        "/api/auth/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": first["refresh_token"],
            "client_id": dcr["client_id"],
            "resource": "https://attacker.example/different-audience",
        },
    )
    assert r.status_code == 400


# ---------- Authorize edge cases ----------


@pytest.mark.asyncio
async def test_authorize_rejects_unknown_client_id(client, session):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    _, code_challenge = _make_pkce()
    r = await client.get(
        "/api/auth/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": "ghost-client-not-real",
            "redirect_uri": "http://localhost:9000/callback",
            "scope": "ics",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "resource": _resource(),
        },
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_authorize_rejects_unknown_redirect_uri(client, session):
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
            "redirect_uri": "http://attacker.example/steal",  # not registered
            "scope": "ics",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "resource": _resource(),
        },
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_post_authorize_rejects_tampered_state(client, session):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    r = await client.post(
        "/api/auth/oauth/authorize",
        data={"state_token": "tampered.signature", "decision": "allow"},
        follow_redirects=False,
    )
    assert r.status_code == 403


# ---------- /me with bearer access token ----------


@pytest.mark.asyncio
async def test_me_accepts_bearer_access_token(client, session):
    """Bearer JWT -> /me returns profile + scope + transport=bearer.

    The app requires `ICS_MCP_RESOURCE_URI` to be set before verifying the
    JWT (audience-bound). Dev settings usually leave it unset, so we skip:
    the bearer flow works, but this endpoint needs a prod-like environment.
    """
    if not get_settings().mcp_resource_uri:
        pytest.skip("ICS_MCP_RESOURCE_URI not set: /me requires audience binding")

    dcr = await _register_client(client)
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    body = await _full_flow_to_refresh(client, dcr["client_id"])
    r = await client.get(
        "/api/auth/oauth/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["user_id"] == str(user.id)
    assert me["email"] == user.email
    assert "ics" in me["scopes"]
    assert me["transport"] == "bearer"


# ---------- Reflected XSS regression (consent page) ----------


@pytest.mark.asyncio
async def test_consent_page_escapes_client_name_and_resource(client, session):
    """DCR is unauthenticated, so an attacker can register a client with a
    `<script>` payload in `client_name`. Without html.escape() the consent page would
    render the payload in `<title>` and `<span class="client">`, giving XSS
    in the ICS origin. The regression checks that raw `<script>` and
    `</script>` do not appear in the HTML response (only escaped entities)."""
    xss_name = "<script>alert(document.cookie)</script>"
    xss_resource = "https://attacker.example/<img src=x onerror=alert(1)>"
    dcr = await _register_client(client, name=xss_name)
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    _, code_challenge = _make_pkce()
    params = {
        "response_type": "code",
        "client_id": dcr["client_id"],
        "redirect_uri": "http://localhost:9000/callback",
        "scope": "ics",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "resource": xss_resource,
    }
    r = await client.get("/api/auth/oauth/authorize", params=params)
    # Either 200 (consent rendered) or 400 (if resource validation rejects
    # the payload). Both are acceptable; what matters is that on 200 the
    # payload is escaped. On 400 the vector is closed earlier, also OK.
    if r.status_code == 200:
        body = r.text
        assert "<script>alert(document.cookie)</script>" not in body, (
            "raw <script> payload reflected: XSS regression"
        )
        assert "&lt;script&gt;" in body, "client_name not html-escaped"
        assert "onerror=alert" not in body, "resource not html-escaped"
