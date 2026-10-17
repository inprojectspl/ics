"""Per-IP rate limits on the OAuth authorization-server endpoints."""

from __future__ import annotations

import pytest

from app import ratelimit

AUTHORIZE_PARAMS = {
    "response_type": "code",
    "client_id": "ics-mcp-stdio",
    "redirect_uri": "http://localhost:9000/cb",
    "scope": "ics",
    "code_challenge": "x" * 43,
    "code_challenge_method": "S256",
    "resource": "https://ics.test/mcp",
}


@pytest.mark.asyncio
async def test_token_endpoint_returns_429_after_limit(client):
    for _ in range(ratelimit.OAUTH_TOKEN.limit):
        r = await client.post("/api/auth/oauth/token", data={"grant_type": "bogus"})
        assert r.status_code == 400
    r = await client.post("/api/auth/oauth/token", data={"grant_type": "bogus"})
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) >= 1


@pytest.mark.asyncio
async def test_authorize_get_returns_429_after_limit(client):
    for _ in range(ratelimit.OAUTH_AUTHORIZE.limit):
        r = await client.get(
            "/api/auth/oauth/authorize", params=AUTHORIZE_PARAMS, follow_redirects=False
        )
        assert r.status_code != 429
    r = await client.get(
        "/api/auth/oauth/authorize", params=AUTHORIZE_PARAMS, follow_redirects=False
    )
    assert r.status_code == 429


@pytest.mark.asyncio
async def test_authorize_post_shares_the_authorize_bucket(client):
    for _ in range(ratelimit.OAUTH_AUTHORIZE.limit):
        r = await client.post(
            "/api/auth/oauth/authorize", data={"state_token": "x", "decision": "deny"}
        )
        assert r.status_code == 403
    r = await client.post(
        "/api/auth/oauth/authorize", data={"state_token": "x", "decision": "deny"}
    )
    assert r.status_code == 429
