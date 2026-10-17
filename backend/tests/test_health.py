"""Smoke tests for `routes/health.py`.

Endpoints:
- /healthz: always 200, server ping.
- /readyz: 200 if the DB answers SELECT 1; we check it does not break.
- /health/jobs: `ok` if the Arq heartbeat in Redis is fresh, `unknown` otherwise.
- /.well-known/oauth-protected-resource: RFC 9728 metadata; we verify the structure.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_healthz_returns_ok(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_readyz_returns_ready_when_db_up(client):
    r = await client.get("/readyz")
    assert r.status_code == 200
    assert r.json() == {"status": "ready"}


@pytest.mark.asyncio
async def test_jobs_health_returns_unknown_when_no_heartbeat(client):
    """Without an Arq worker, Redis has no `arq:health-check`: the endpoint
    returns `unknown`, not 503: the JSON informs, but the request does not
    fail."""
    r = await client.get("/health/jobs")
    assert r.status_code == 200
    payload = r.json()
    assert "status" in payload
    assert payload["status"] in ("ok", "unknown")
    assert "heartbeat" in payload


@pytest.mark.asyncio
async def test_oauth_protected_resource_metadata_shape(client):
    """RFC 9728: discovery for MCP clients. Required fields: `resource`,
    `authorization_servers`, `bearer_methods_supported`."""
    r = await client.get("/.well-known/oauth-protected-resource")
    assert r.status_code == 200
    meta = r.json()
    assert "resource" in meta
    assert isinstance(meta.get("authorization_servers"), list)
    assert meta.get("authorization_servers"), "at least one authorization server is required"
    assert meta.get("bearer_methods_supported") == ["header"]
    assert "ics" in meta.get("scopes_supported", [])


# ---------- Security headers middleware ----------


@pytest.mark.asyncio
async def test_security_headers_present_on_api(client):
    """Every response from the main app/API must have X-Frame-Options,
    X-Content-Type-Options, Referrer-Policy. Without them the SPA is exposed
    to clickjacking, MIME confusion and referrer leakage."""
    r = await client.get("/healthz")
    assert r.headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


@pytest.mark.asyncio
async def test_security_headers_present_on_error_response(client):
    """The headers must be sent on 4xx too, otherwise an error page could be
    embedded in an iframe."""
    r = await client.get("/api/auth/me")  # 401 without a session
    assert r.status_code == 401
    assert r.headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
