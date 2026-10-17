"""Tests for `routes/bindings.py`: bindings CRUD and key rotation.

The sync flow (`POST /api/bindings/{id}/sync`) is involved: it needs a signed
manifest, a ZIP bundle and a fresh commit timestamp. It is covered indirectly
by `test_signing.py` (low-level Ed25519) plus a smoke test via unauthorized sync.

Covers:
- POST /api/bindings: happy path (returns private_key once), 403 for a
  non-owner of the asset.
- GET /api/bindings/{id} and listing per asset_id.
- GET /api/bindings/providers: provider list for the UI.
- PATCH: URL change, webhook URL validation and atomic validation of the
  (provider, webhook_url) pair.
- POST /rotate: replaces the key, clears last_sync state.
- DELETE.
- POST /sync: 404 for an unknown binding_id, 403 for an invalid signature.
"""

from __future__ import annotations

import json

import pytest

from app import signing
from tests.conftest import login_as as _login
from tests.conftest import mk_asset, mk_user

# ---------- CREATE ----------


@pytest.mark.asyncio
async def test_create_binding_returns_private_key_only_once(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)

    r = await client.post(
        "/api/bindings",
        json={
            "asset_id": str(asset.id),
            "gitlab_project_url": "https://gitlab.example.com/team/repo",
        },
    )
    assert r.status_code == 201, r.text
    payload = r.json()
    assert "private_key" in payload, "private_key is issued only on create"
    assert "public_key" in payload
    assert payload["asset_id"] == str(asset.id)

    # GET does not return private_key: it is one-shot.
    binding_id = payload["id"]
    g = await client.get(f"/api/bindings/{binding_id}")
    assert g.status_code == 200
    assert "private_key" not in g.json()


@pytest.mark.asyncio
async def test_create_binding_rejects_non_owner(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    stranger = await mk_user(session)
    await session.commit()
    await _login(client, stranger)

    r = await client.post(
        "/api/bindings",
        json={"asset_id": str(asset.id)},
    )
    # 404 hides the existence of another user's asset (info leak prevention).
    assert r.status_code in (403, 404)


@pytest.mark.asyncio
async def test_editor_cannot_create_or_list_bindings(client, session):
    """Create and list follow the same owner-only rule as rotate and delete."""
    from app.models import AssetShare

    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    editor = await mk_user(session)
    session.add(
        AssetShare(asset_id=asset.id, user_id=editor.id, role="editor", granted_by=owner.id)
    )
    await session.commit()
    await _login(client, editor)

    r = await client.post("/api/bindings", json={"asset_id": str(asset.id)})
    assert r.status_code == 404, r.text
    r = await client.get("/api/bindings", params={"asset_id": str(asset.id)})
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_create_binding_rejects_invalid_webhook_url(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)

    r = await client.post(
        "/api/bindings",
        json={"asset_id": str(asset.id), "webhook_url": "not-a-real-url"},
    )
    assert r.status_code == 400


# ---------- LIST / GET ----------


@pytest.mark.asyncio
async def test_list_bindings_for_asset_returns_only_owners(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)

    create_r = await client.post(
        "/api/bindings",
        json={"asset_id": str(asset.id)},
    )
    assert create_r.status_code == 201

    list_r = await client.get(f"/api/bindings?asset_id={asset.id}")
    assert list_r.status_code == 200
    rows = list_r.json()
    assert len(rows) == 1
    assert rows[0]["asset_id"] == str(asset.id)


# ---------- PATCH ----------


@pytest.mark.asyncio
async def test_patch_binding_updates_url(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)

    create_r = await client.post(
        "/api/bindings",
        json={"asset_id": str(asset.id)},
    )
    binding_id = create_r.json()["id"]

    patch_r = await client.patch(
        f"/api/bindings/{binding_id}",
        json={"gitlab_project_url": "https://gitlab.example.com/new/repo"},
    )
    assert patch_r.status_code == 200
    assert patch_r.json()["gitlab_project_url"] == "https://gitlab.example.com/new/repo"


# ---------- ROTATE ----------


@pytest.mark.asyncio
async def test_rotate_binding_replaces_keypair(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)

    create_r = await client.post("/api/bindings", json={"asset_id": str(asset.id)})
    initial = create_r.json()

    rotate_r = await client.post(f"/api/bindings/{initial['id']}/rotate")
    assert rotate_r.status_code == 200
    rotated = rotate_r.json()
    assert rotated["public_key"] != initial["public_key"]
    assert rotated["private_key"] != initial["private_key"]
    # Rotation resets last_sync*: no state from the old key stays "valid".
    assert rotated["last_sync_at"] is None
    assert rotated["last_sync_commit_sha"] is None


# ---------- DELETE ----------


@pytest.mark.asyncio
async def test_delete_binding_makes_it_gone(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)

    create_r = await client.post("/api/bindings", json={"asset_id": str(asset.id)})
    binding_id = create_r.json()["id"]

    del_r = await client.delete(f"/api/bindings/{binding_id}")
    assert del_r.status_code == 204

    get_r = await client.get(f"/api/bindings/{binding_id}")
    assert get_r.status_code in (403, 404)


# ---------- SYNC (security gate) ----------


@pytest.mark.asyncio
async def test_sync_returns_404_for_unknown_binding(client):
    """An unauthorized sync, even without a signature, returns 404 when the
    binding does not exist. No info leak about whether the ID ever existed."""
    files = {
        "manifest": ("m.json", b"{}", "application/json"),
        "signature": ("s.b64", b"sig", "application/octet-stream"),
        "bundle": ("b.zip", b"zip", "application/zip"),
    }
    r = await client.post(
        "/api/bindings/00000000-0000-0000-0000-000000000001/sync",
        files=files,
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_sync_rejects_bad_signature(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)

    create_r = await client.post("/api/bindings", json={"asset_id": str(asset.id)})
    binding_id = create_r.json()["id"]

    # Log out: sync does not need a session (auth via signature).
    await client.post("/api/auth/logout")

    manifest = json.dumps(
        {
            "binding_id": binding_id,
            "commit_sha": "abc123",
            "commit_timestamp": "2026-01-01T00:00:00Z",
            "bundle_sha256": "0" * 64,
        }
    ).encode()
    # Foreign key: generate a new keypair and sign with its private key,
    # but the server has a different `public_key` stored -> verify fails.
    other_priv, _other_pub = signing.generate_keypair()
    bad_sig = signing.sign(manifest, other_priv)

    files = {
        "manifest": ("m.json", manifest, "application/json"),
        "signature": ("s.b64", bad_sig.encode(), "application/octet-stream"),
        "bundle": ("b.zip", b"", "application/zip"),
    }
    r = await client.post(f"/api/bindings/{binding_id}/sync", files=files)
    assert r.status_code == 403
    assert r.json()["code"] == "bad_signature"


@pytest.mark.asyncio
async def test_sync_rejects_manifest_binding_id_mismatch(client, session):
    """Manifest signed with the correct key, but its `binding_id` points at a
    different binding than the URL: 400."""
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)

    create_r = await client.post("/api/bindings", json={"asset_id": str(asset.id)})
    binding_id = create_r.json()["id"]
    private_key = create_r.json()["private_key"]
    await client.post("/api/auth/logout")

    # Manifest with a different binding_id than the URL.
    fake_binding_id = "11111111-2222-3333-4444-555555555555"
    manifest = json.dumps(
        {
            "binding_id": fake_binding_id,
            "commit_sha": "abc123",
            "commit_timestamp": "2026-01-01T00:00:00Z",
            "bundle_sha256": "0" * 64,
        }
    ).encode()
    sig = signing.sign(manifest, private_key)

    files = {
        "manifest": ("m.json", manifest, "application/json"),
        "signature": ("s.b64", sig.encode(), "application/octet-stream"),
        "bundle": ("b.zip", b"", "application/zip"),
    }
    r = await client.post(f"/api/bindings/{binding_id}/sync", files=files)
    assert r.status_code == 400
    assert r.json()["code"] == "manifest_mismatch"


@pytest.mark.asyncio
async def test_sync_rejects_bundle_sha_mismatch(client, session):
    """The manifest declares a bundle hash that does not match the real bundle."""
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)

    create_r = await client.post("/api/bindings", json={"asset_id": str(asset.id)})
    binding_id = create_r.json()["id"]
    private_key = create_r.json()["private_key"]
    await client.post("/api/auth/logout")

    bundle_bytes = b"some content"
    # Wrong hash in the manifest.
    manifest = json.dumps(
        {
            "binding_id": binding_id,
            "commit_sha": "deadbeef",
            "commit_timestamp": "2026-01-01T00:00:00Z",
            "bundle_sha256": "f" * 64,  # bad hash
        }
    ).encode()
    sig = signing.sign(manifest, private_key)

    files = {
        "manifest": ("m.json", manifest, "application/json"),
        "signature": ("s.b64", sig.encode(), "application/octet-stream"),
        "bundle": ("b.zip", bundle_bytes, "application/zip"),
    }
    r = await client.post(f"/api/bindings/{binding_id}/sync", files=files)
    assert r.status_code == 400
    assert r.json()["code"] == "bundle_hash_mismatch"


@pytest.mark.asyncio
async def test_sync_rejects_future_timestamp(client, session):
    """Timestamp in the future (>5 min clock skew) -> 400."""
    import hashlib
    from datetime import UTC, datetime, timedelta

    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)

    create_r = await client.post("/api/bindings", json={"asset_id": str(asset.id)})
    binding_id = create_r.json()["id"]
    private_key = create_r.json()["private_key"]
    await client.post("/api/auth/logout")

    bundle_bytes = b""
    future = (datetime.now(UTC) + timedelta(hours=24)).isoformat().replace("+00:00", "Z")
    manifest = json.dumps(
        {
            "binding_id": binding_id,
            "commit_sha": "future",
            "commit_timestamp": future,
            "bundle_sha256": hashlib.sha256(bundle_bytes).hexdigest(),
        }
    ).encode()
    sig = signing.sign(manifest, private_key)

    files = {
        "manifest": ("m.json", manifest, "application/json"),
        "signature": ("s.b64", sig.encode(), "application/octet-stream"),
        "bundle": ("b.zip", bundle_bytes, "application/zip"),
    }
    r = await client.post(f"/api/bindings/{binding_id}/sync", files=files)
    assert r.status_code == 400
    assert r.json()["code"] == "commit_from_future"


@pytest.mark.asyncio
async def test_sync_rejects_invalid_manifest_json(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)

    create_r = await client.post("/api/bindings", json={"asset_id": str(asset.id)})
    binding_id = create_r.json()["id"]
    private_key = create_r.json()["private_key"]
    await client.post("/api/auth/logout")

    bad_manifest = b'{"not": "valid manifest at all"}'
    sig = signing.sign(bad_manifest, private_key)
    files = {
        "manifest": ("m.json", bad_manifest, "application/json"),
        "signature": ("s.b64", sig.encode(), "application/octet-stream"),
        "bundle": ("b.zip", b"", "application/zip"),
    }
    r = await client.post(f"/api/bindings/{binding_id}/sync", files=files)
    assert r.status_code == 400
    assert r.json()["code"] == "manifest_invalid"


# ---------- PROVIDER VALIDATION + /providers ----------

_GC_URL = "https://chat.googleapis.com/v1/spaces/AAA/messages?key=x&token=y"


@pytest.mark.asyncio
async def test_list_providers_requires_auth(client):
    r = await client.get("/api/bindings/providers")
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_list_providers_returns_google_chat(client, session):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)
    r = await client.get("/api/bindings/providers")
    assert r.status_code == 200
    rows = r.json()
    by_id = {row["id"]: row for row in rows}
    assert "google_chat" in by_id
    assert by_id["google_chat"]["display_name"] == "Google Chat"
    assert "chat.googleapis.com" in by_id["google_chat"]["url_hint"]


@pytest.mark.asyncio
async def test_create_binding_rejects_webhook_without_provider(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)
    r = await client.post(
        "/api/bindings",
        json={"asset_id": str(asset.id), "webhook_url": _GC_URL},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_create_binding_rejects_provider_without_webhook(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)
    r = await client.post(
        "/api/bindings",
        json={"asset_id": str(asset.id), "provider": "google_chat"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_create_binding_rejects_url_not_matching_provider(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)
    r = await client.post(
        "/api/bindings",
        json={
            "asset_id": str(asset.id),
            "provider": "google_chat",
            "webhook_url": "https://hooks.slack.com/services/T00/B00/abc",
        },
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_create_binding_rejects_unknown_provider(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)
    r = await client.post(
        "/api/bindings",
        json={
            "asset_id": str(asset.id),
            "provider": "slack",  # not in the enum
            "webhook_url": "https://hooks.slack.com/x",
        },
    )
    # Pydantic rejects an unknown enum before the route runs; 422 and 400 are
    # equally fine, both signal invalid input.
    assert r.status_code in (400, 422)


@pytest.mark.asyncio
async def test_create_binding_accepts_google_chat_pair(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)
    r = await client.post(
        "/api/bindings",
        json={
            "asset_id": str(asset.id),
            "provider": "google_chat",
            "webhook_url": _GC_URL,
        },
    )
    assert r.status_code == 201, r.text
    payload = r.json()
    assert payload["provider"] == "google_chat"
    assert payload["webhook_url"] == _GC_URL


@pytest.mark.asyncio
async def test_patch_binding_rejects_pair_partial(client, session):
    """Patching one field of the pair (provider or webhook_url) without the
    other = 400. Validation is atomic so the DB invariant stays consistent."""
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)
    create_r = await client.post(
        "/api/bindings",
        json={
            "asset_id": str(asset.id),
            "provider": "google_chat",
            "webhook_url": _GC_URL,
        },
    )
    binding_id = create_r.json()["id"]

    r = await client.patch(
        f"/api/bindings/{binding_id}",
        json={"webhook_url": "https://chat.googleapis.com/v1/spaces/B/messages"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_patch_binding_clears_pair_when_both_null(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)
    create_r = await client.post(
        "/api/bindings",
        json={
            "asset_id": str(asset.id),
            "provider": "google_chat",
            "webhook_url": _GC_URL,
        },
    )
    binding_id = create_r.json()["id"]

    r = await client.patch(
        f"/api/bindings/{binding_id}",
        json={"provider": None, "webhook_url": None},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] is None
    assert body["webhook_url"] is None


@pytest.mark.asyncio
async def test_patch_binding_swaps_pair(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)
    create_r = await client.post("/api/bindings", json={"asset_id": str(asset.id)})
    binding_id = create_r.json()["id"]
    new_url = "https://chat.googleapis.com/v1/spaces/NEW/messages?key=z&token=q"

    r = await client.patch(
        f"/api/bindings/{binding_id}",
        json={"provider": "google_chat", "webhook_url": new_url},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "google_chat"
    assert body["webhook_url"] == new_url


# ---------- PATCH webhook + empty listing ----------


@pytest.mark.asyncio
async def test_patch_binding_updates_webhook_url(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)

    create = await client.post("/api/bindings", json={"asset_id": str(asset.id)})
    binding_id = create.json()["id"]

    new_url = "https://chat.googleapis.com/v1/spaces/X/messages?key=a&token=b"
    r = await client.patch(
        f"/api/bindings/{binding_id}",
        json={"provider": "google_chat", "webhook_url": new_url},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["webhook_url"] == new_url
    assert body["provider"] == "google_chat"


@pytest.mark.asyncio
async def test_patch_binding_rejects_invalid_webhook(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)

    create = await client.post("/api/bindings", json={"asset_id": str(asset.id)})
    binding_id = create.json()["id"]

    r = await client.patch(
        f"/api/bindings/{binding_id}",
        json={"provider": "google_chat", "webhook_url": "not-a-url"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_list_bindings_empty_for_fresh_asset(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)

    r = await client.get(f"/api/bindings?asset_id={asset.id}")
    assert r.status_code == 200
    assert r.json() == []
