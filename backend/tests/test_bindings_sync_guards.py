"""Cheap-rejection guards on the unauthenticated binding sync endpoint."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from app import ratelimit, signing
from app.config import get_settings
from app.models import GitLabBinding
from app.services import asset_versions
from tests.conftest import login_as as _login
from tests.conftest import mk_asset, mk_user


async def _new_binding(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)
    r = await client.post("/api/bindings", json={"asset_id": str(asset.id)})
    await client.post("/api/auth/logout")
    return r.json()["id"], r.json()["private_key"]


def _files(binding_id, private_key, bundle, *, ts, bundle_sha=None):
    manifest = json.dumps(
        {
            "binding_id": binding_id,
            "commit_sha": "abc123",
            "commit_timestamp": ts.isoformat().replace("+00:00", "Z"),
            "bundle_sha256": bundle_sha or hashlib.sha256(bundle).hexdigest(),
        }
    ).encode()
    return {
        "manifest": ("m.json", manifest, "application/json"),
        "signature": ("s.b64", signing.sign(manifest, private_key).encode(), "text/plain"),
        "bundle": ("b.tar.gz", bundle, "application/gzip"),
    }


@pytest.fixture
def extract_calls(monkeypatch):
    calls = []

    async def fake_extract(**kwargs):
        calls.append(kwargs)
        return [], 0

    monkeypatch.setattr(asset_versions, "extract_to_storage", fake_extract)
    return calls


@pytest.mark.asyncio
async def test_oversized_body_is_rejected_before_storage(
    client, session, monkeypatch, extract_calls
):
    binding_id, key = await _new_binding(client, session)
    monkeypatch.setattr(get_settings(), "max_request_bytes", 4096)
    files = _files(binding_id, key, b"x" * 10_000, ts=datetime.now(UTC))
    r = await client.post(f"/api/bindings/{binding_id}/sync", files=files)
    assert r.status_code == 413
    assert extract_calls == []


@pytest.mark.asyncio
async def test_replay_is_refused_before_the_bundle_is_read(client, session, extract_calls):
    binding_id, key = await _new_binding(client, session)
    binding = await session.get(GitLabBinding, binding_id)
    binding.last_sync_timestamp = datetime.now(UTC)
    await session.commit()

    # The bundle hash is deliberately wrong: reading the bundle first would
    # answer 400, so a 409 proves the replay check ran before it.
    old = datetime.now(UTC) - timedelta(hours=1)
    files = _files(binding_id, key, b"bundle", ts=old, bundle_sha="0" * 64)
    r = await client.post(f"/api/bindings/{binding_id}/sync", files=files)
    assert r.status_code == 409
    assert extract_calls == []


@pytest.mark.asyncio
async def test_sync_is_rate_limited_per_ip(client):
    unknown = "00000000-0000-0000-0000-000000000000"
    files = {
        "manifest": ("m.json", b"{}", "application/json"),
        "signature": ("s.b64", b"x", "text/plain"),
        "bundle": ("b.tar.gz", b"", "application/gzip"),
    }
    for _ in range(ratelimit.BINDING_SYNC.limit):
        r = await client.post(f"/api/bindings/{unknown}/sync", files=files)
        assert r.status_code == 404
    r = await client.post(f"/api/bindings/{unknown}/sync", files=files)
    assert r.status_code == 429


@pytest.mark.asyncio
async def test_chunked_body_over_limit_is_cut_off(monkeypatch):
    from starlette.exceptions import HTTPException

    from app.body_limit import BodySizeLimitMiddleware

    monkeypatch.setattr(get_settings(), "max_request_bytes", 10)
    chunks = [
        {"type": "http.request", "body": b"x" * 8, "more_body": True},
        {"type": "http.request", "body": b"x" * 8, "more_body": False},
    ]

    async def receive():
        return chunks.pop(0)

    async def app(scope, receive, send):
        while (await receive()).get("more_body"):
            pass

    middleware = BodySizeLimitMiddleware(app)
    with pytest.raises(HTTPException) as exc:
        await middleware({"type": "http", "headers": []}, receive, None)
    assert exc.value.status_code == 413
