"""Cold OAuth connections survive login without accepting an external return URL."""

from urllib.parse import parse_qs, urlencode, urlsplit

import pytest

from app.config import get_settings
from app.redis_client import get_redis
from tests.conftest import (
    STATE_TOKEN_RE,
    login_as,
    make_pkce,
    mk_user,
    mock_google_oauth,
    patch_google_creds,
    register_oauth_client,
    resource_uri,
)


async def _cold_authorization(client):
    registered = await register_oauth_client(client, name="Cold login")
    verifier, challenge = make_pkce()
    params = {
        "response_type": "code",
        "client_id": registered["client_id"],
        "redirect_uri": "http://localhost:9000/callback",
        "scope": "ics",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": resource_uri(),
        "state": "connection+state&x=y#fragment%20?=ąć",
        "nonce": "nonce+with&reserved=characters",
    }
    path = f"/api/auth/oauth/authorize?{urlencode(params)}"
    response = await client.get(path, follow_redirects=False)
    assert response.status_code == 307
    location = urlsplit(response.headers["location"])
    assert location.fragment.startswith("login?")
    next_path = parse_qs(location.fragment.removeprefix("login?"))["next"][0]
    assert next_path == path
    return next_path, params, verifier


@pytest.mark.asyncio
async def test_cold_password_login_returns_to_the_original_consent(client, session):
    next_path, params, _ = await _cold_authorization(client)
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)
    consent = await client.get(next_path)
    assert consent.status_code == 200
    from app.oauth.state import verify

    state = verify(get_settings(), STATE_TOKEN_RE.search(consent.text).group(1))
    assert state["client_id"] == params["client_id"]
    assert state["state"] == params["state"]
    assert state["nonce"] == params["nonce"]


@pytest.mark.asyncio
async def test_cold_google_login_resumes_consent_and_completes_pkce(client, session, monkeypatch):
    next_path, params, verifier = await _cold_authorization(client)
    user = await mk_user(session)
    await session.commit()
    patch_google_creds(monkeypatch)
    oauth = mock_google_oauth({"userinfo": {"email": user.email, "email_verified": True}})
    monkeypatch.setattr("app.routes.auth.google.get_oauth", lambda: oauth)

    login = await client.get("/api/auth/google/login", params={"next": next_path})
    assert login.status_code == 302
    state = oauth.google.authorize_redirect.call_args.kwargs["state"]
    callback = await client.get(
        "/api/auth/google/callback", params={"code": "google", "state": state}
    )
    assert callback.status_code == 302
    assert callback.headers["location"] == f"{get_settings().base_url}{next_path}"
    assert await get_redis().get(f"google_login_return:{state}") is None

    consent = await client.get(next_path)
    assert consent.status_code == 200
    grant = await client.post(
        "/api/auth/oauth/authorize",
        data={"decision": "allow", "state_token": STATE_TOKEN_RE.search(consent.text).group(1)},
    )
    assert grant.status_code == 302
    returned = parse_qs(urlsplit(grant.headers["location"]).query)
    assert returned["state"] == [params["state"]]
    exchange = {
        "grant_type": "authorization_code",
        "code": returned["code"][0],
        "client_id": params["client_id"],
        "redirect_uri": params["redirect_uri"],
        "resource": params["resource"],
        "code_verifier": "wrong-verifier",
    }
    rejected = await client.post("/api/auth/oauth/token", data=exchange)
    assert rejected.status_code == 400
    assert rejected.json()["code"] == "invalid_grant"
    exchange["code_verifier"] = verifier
    token = await client.post("/api/auth/oauth/token", data=exchange)
    assert token.status_code == 200
    assert token.json()["scope"] == "ics"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    ["https://evil.example/", "//evil.example/", "/\\evil.example/", "/\n/evil.example/", ""],
)
async def test_google_login_rejects_unsafe_returns(client, monkeypatch, path):
    patch_google_creds(monkeypatch)
    oauth = mock_google_oauth({})
    monkeypatch.setattr("app.routes.auth.google.get_oauth", lambda: oauth)
    response = await client.get("/api/auth/google/login", params={"next": path})
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_return_path"
    oauth.google.authorize_redirect.assert_not_called()


@pytest.mark.asyncio
async def test_google_return_storage_is_isolated_by_oidc_state(client, session, monkeypatch):
    # This checks Redis destination isolation with a mocked provider. Authlib
    # controls which pending OIDC states remain valid in the browser session.
    user = await mk_user(session)
    await session.commit()
    patch_google_creds(monkeypatch)
    oauth = mock_google_oauth({"userinfo": {"email": user.email, "email_verified": True}})
    monkeypatch.setattr("app.routes.auth.google.get_oauth", lambda: oauth)
    states = []
    for path in ("/projects/first", "/projects/second"):
        await client.get("/api/auth/google/login", params={"next": path})
        states.append(oauth.google.authorize_redirect.call_args.kwargs["state"])
    assert states[0] != states[1]
    for state, path in zip(states, ("/projects/first", "/projects/second"), strict=True):
        assert await get_redis().get(f"google_login_return:{state}") == (
            f"{get_settings().base_url}{path}"
        )
    for state, path in zip(states, ("/projects/first", "/projects/second"), strict=True):
        response = await client.get("/api/auth/google/callback", params={"state": state})
        assert response.headers["location"] == f"{get_settings().base_url}{path}"
        assert await get_redis().get(f"google_login_return:{state}") is None


@pytest.mark.asyncio
async def test_rejected_provider_state_does_not_consume_the_return(client, monkeypatch):
    patch_google_creds(monkeypatch)
    oauth = mock_google_oauth(raise_on_token=RuntimeError("state mismatch"))
    monkeypatch.setattr("app.routes.auth.google.get_oauth", lambda: oauth)
    path = "/api/auth/oauth/authorize?state=original"
    await client.get("/api/auth/google/login", params={"next": path})
    state = oauth.google.authorize_redirect.call_args.kwargs["state"]
    response = await client.get("/api/auth/google/callback", params={"state": state})
    assert response.status_code == 400
    assert response.json()["code"] == "google_rejected"
    assert "location" not in response.headers
    assert await get_redis().get(f"google_login_return:{state}") == (
        f"{get_settings().base_url}{path}"
    )
    assert (await client.get("/api/auth/oauth/me")).status_code == 401
