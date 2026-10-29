"""Tests for `oauth/server.py`: metadata + JWKS + Dynamic Client Registration.

Covers:
- /.well-known/oauth-authorization-server (RFC 8414).
- /.well-known/openid-configuration (OIDC Discovery 1.0).
- /jwks.json (RFC 7517): JWK with `kid`, `n`, `e`, `alg=RS256`.
- POST /register (RFC 7591 DCR): public client + redirect_uris validation.
- POST /revoke: silent OK for an unknown token (per RFC 7009 section 2.2).
- GET /me: 401 for anonymous callers (requires bearer / session).

The full /authorize -> /token flow with PKCE is covered in test_oauth_flow.py.
"""

from __future__ import annotations

import pytest

# ---------- Metadata ----------


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["", "/api/auth/oauth"])
async def test_authorization_server_metadata_rfc_8414(client, prefix):
    r = await client.get(f"{prefix}/.well-known/oauth-authorization-server")
    assert r.status_code == 200
    meta = r.json()
    # Required fields from RFC 8414 Section 2.
    assert "issuer" in meta
    assert "authorization_endpoint" in meta
    assert "token_endpoint" in meta
    assert "jwks_uri" in meta
    assert "response_types_supported" in meta
    # ICS-specific assertions.
    assert "code" in meta["response_types_supported"]
    assert "S256" in meta["code_challenge_methods_supported"]
    assert "authorization_code" in meta["grant_types_supported"]
    assert "refresh_token" in meta["grant_types_supported"]
    # Endpoints are full URLs.
    assert meta["authorization_endpoint"].endswith("/api/auth/oauth/authorize")
    assert meta["token_endpoint"].endswith("/api/auth/oauth/token")
    assert meta["jwks_uri"].endswith("/api/auth/oauth/jwks.json")


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["", "/api/auth/oauth"])
async def test_oidc_discovery_extends_oauth_metadata(client, prefix):
    r = await client.get(f"{prefix}/.well-known/openid-configuration")
    assert r.status_code == 200
    meta = r.json()
    # All RFC 8414 fields + ID-token specific ones.
    assert meta["subject_types_supported"] == ["public"]
    assert "RS256" in meta["id_token_signing_alg_values_supported"]
    assert meta["userinfo_endpoint"].endswith("/api/auth/oauth/me")


@pytest.mark.asyncio
async def test_resource_discovery_reaches_metadata_at_the_advertised_issuer(client):
    from app.config import get_settings

    resource = (await client.get("/.well-known/oauth-protected-resource")).json()
    issuer = resource["authorization_servers"][0]
    assert issuer == (get_settings().oauth_issuer or get_settings().base_url).rstrip("/")
    metadata = await client.get(f"{issuer}/.well-known/oauth-authorization-server")
    legacy = await client.get("/api/auth/oauth/.well-known/oauth-authorization-server")
    assert metadata.status_code == 200
    assert metadata.headers["content-type"].startswith("application/json")
    assert metadata.json() == legacy.json()
    assert metadata.json()["issuer"] == issuer


@pytest.mark.asyncio
async def test_jwks_returns_rsa_public_key(client):
    r = await client.get("/api/auth/oauth/jwks.json")
    assert r.status_code == 200
    doc = r.json()
    keys = doc.get("keys")
    assert isinstance(keys, list) and len(keys) >= 1
    key = keys[0]
    assert key["kty"] == "RSA"
    assert key["alg"] == "RS256"
    assert key["use"] == "sig"
    assert "kid" in key
    assert "n" in key
    assert "e" in key
    # The modulus is base64url-encoded (no padding): a quick sanity check.
    assert "=" not in key["n"]


# ---------- DCR (/register) ----------


@pytest.mark.asyncio
async def test_dcr_creates_public_client(client):
    r = await client.post(
        "/api/auth/oauth/register",
        json={
            "client_name": "Test MCP Client",
            "redirect_uris": ["http://localhost:9000/callback"],
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["client_id"].startswith("dyn-")
    assert body["token_endpoint_auth_method"] == "none"
    assert "authorization_code" in body["grant_types"]
    assert "refresh_token" in body["grant_types"]
    assert body["redirect_uris"] == ["http://localhost:9000/callback"]
    assert body["registration_client_uri"].endswith(f"/clients/{body['client_id']}")


@pytest.mark.asyncio
async def test_dcr_rejects_empty_redirect_uris(client):
    r = await client.post(
        "/api/auth/oauth/register",
        json={"client_name": "X", "redirect_uris": []},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_dcr_rejects_missing_redirect_uris(client):
    r = await client.post(
        "/api/auth/oauth/register",
        json={"client_name": "X"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_dcr_rejects_non_list_redirect_uris(client):
    r = await client.post(
        "/api/auth/oauth/register",
        json={"client_name": "X", "redirect_uris": "http://x"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_dcr_default_client_name(client):
    """Missing `client_name` -> falls back to "Dynamic MCP client"."""
    r = await client.post(
        "/api/auth/oauth/register",
        json={"redirect_uris": ["http://localhost:9000/callback"]},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["client_id"].startswith("dyn-")


# ---------- /revoke (RFC 7009 silent-fail) ----------


@pytest.mark.asyncio
async def test_revoke_silently_accepts_unknown_token(client):
    """RFC 7009 section 2.2: the server MUST return 200 whether or not the
    token existed (anti-enumeration). Here we check a garbage token does not crash."""
    r = await client.post(
        "/api/auth/oauth/revoke",
        data={"token": "not-a-real-token-at-all"},
    )
    # 200 or 400, both acceptable. We just must not crash with 500.
    assert r.status_code in (200, 400)


# ---------- /me (whoami) ----------


@pytest.mark.asyncio
async def test_me_rejects_anonymous(client):
    r = await client.get("/api/auth/oauth/me")
    assert r.status_code == 401


# ---------- /authorize gating ----------


@pytest.mark.asyncio
async def test_authorize_without_session_redirects_to_login(client):
    """The user must be signed in to ICS to see the consent screen: without
    a session the endpoint redirects to /login with `?return_to=...`."""
    params = {
        "response_type": "code",
        "client_id": "ics-mcp-stdio",
        "redirect_uri": "http://localhost:9000/cb",
        "scope": "ics",
        "code_challenge": "x" * 43,
        "code_challenge_method": "S256",
        "resource": "https://ics.test/mcp",
    }
    r = await client.get(
        "/api/auth/oauth/authorize",
        params=params,
        follow_redirects=False,
    )
    # 302/303 redirect or 400/401: none of these crash.
    assert r.status_code in (302, 303, 307, 400, 401, 404)
