"""Tests for the signed sync endpoint in `routes/bindings.py`.

Covers the happy path and the rejections that must leave the asset and the
storage untouched: replay, soft-deleted asset, empty or unsafe bundle,
commit timestamp from the future, kind mismatch and owner quota.
Cheap-rejection guards (body size, rate limit) are in `test_bindings_sync_guards.py`.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
from datetime import UTC, datetime, timedelta

import pytest

from app import signing
from app.models import User
from tests.conftest import login_as as _login
from tests.conftest import make_tar_gz as _make_tar_gz
from tests.conftest import mk_asset, mk_user


async def _new_binding(client, session, *, kind="md_collection", entry_path="README.md"):
    """Owner + asset + binding created through the API. Returns (asset, binding_id, key)."""
    owner = await mk_user(session)
    asset = await mk_asset(session, owner, kind=kind, entry_path=entry_path)
    await session.commit()
    await _login(client, owner)
    r = await client.post("/api/bindings", json={"asset_id": str(asset.id)})
    assert r.status_code == 201, r.text
    await client.post("/api/auth/logout")
    return asset, r.json()["id"], r.json()["private_key"]


def _iso(ts: datetime) -> str:
    return ts.isoformat().replace("+00:00", "Z")


def _files(binding_id, private_key, bundle: bytes, *, ts: str | None = None, sha="deadbeef1234"):
    manifest = json.dumps(
        {
            "binding_id": binding_id,
            "commit_sha": sha,
            "commit_timestamp": ts or _iso(datetime.now(UTC)),
            "bundle_sha256": hashlib.sha256(bundle).hexdigest(),
        }
    ).encode()
    sig = signing.sign(manifest, private_key)
    return {
        "manifest": ("m.json", manifest, "application/json"),
        "signature": ("s.b64", sig.encode(), "application/octet-stream"),
        "bundle": ("b.tar.gz", bundle, "application/gzip"),
    }


def _tar_with_absolute_member() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        data = b"# pwned\n"
        info = tarfile.TarInfo(name="/tmp/evil.md")
        info.size = len(data)
        t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _stored_files(root: str) -> list[str]:
    return [os.path.join(d, f) for d, _, files in os.walk(root) for f in files]


async def _assert_untouched(session, asset, fs_storage) -> None:
    await session.refresh(asset)
    assert asset.version == 1
    assert _stored_files(fs_storage) == []


# ---------- happy path ----------


@pytest.mark.asyncio
async def test_sync_happy_path_bumps_asset_version(client, session, fs_storage):
    asset, binding_id, key = await _new_binding(client, session)
    bundle = _make_tar_gz({"README.md": b"# v2\n", "extra.md": b"# extra\n"})

    r = await client.post(f"/api/bindings/{binding_id}/sync", files=_files(binding_id, key, bundle))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["version"] == 2
    assert body["file_count"] == 2
    assert body["commit_sha"] == "deadbeef1234"

    await session.refresh(asset)
    assert asset.version == 2


@pytest.mark.asyncio
async def test_sync_accepts_timestamp_within_clock_skew(client, session, fs_storage):
    """CI clocks may run ahead; up to 5 minutes is tolerated."""
    _asset, binding_id, key = await _new_binding(client, session)
    bundle = _make_tar_gz({"README.md": b"# v2\n"})
    ts = _iso(datetime.now(UTC) + timedelta(minutes=4))

    r = await client.post(
        f"/api/bindings/{binding_id}/sync", files=_files(binding_id, key, bundle, ts=ts)
    )
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_sync_accepts_naive_timestamp_as_utc(client, session, fs_storage):
    _asset, binding_id, key = await _new_binding(client, session)
    bundle = _make_tar_gz({"README.md": b"# v2\n"})
    naive = datetime.now(UTC).replace(tzinfo=None).isoformat()

    r = await client.post(
        f"/api/bindings/{binding_id}/sync", files=_files(binding_id, key, bundle, ts=naive)
    )
    assert r.status_code == 201, r.text


# ---------- rejections ----------


@pytest.mark.asyncio
async def test_sync_replay_returns_409(client, session, fs_storage):
    """A second push with the same timestamp is a replay."""
    _asset, binding_id, key = await _new_binding(client, session)
    bundle = _make_tar_gz({"README.md": b"# v\n"})
    files = _files(binding_id, key, bundle, sha="first")

    r1 = await client.post(f"/api/bindings/{binding_id}/sync", files=files)
    assert r1.status_code == 201
    r2 = await client.post(f"/api/bindings/{binding_id}/sync", files=files)
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_sync_rejects_deleted_asset(client, session, fs_storage):
    asset, binding_id, key = await _new_binding(client, session, entry_path="r.md")
    asset.deleted_at = datetime.now(UTC)
    await session.commit()

    bundle = _make_tar_gz({"r.md": b"# x\n"})
    r = await client.post(f"/api/bindings/{binding_id}/sync", files=_files(binding_id, key, bundle))
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_sync_empty_bundle_returns_400(client, session, fs_storage):
    asset, binding_id, key = await _new_binding(client, session, entry_path="r.md")
    bundle = _make_tar_gz({})

    r = await client.post(f"/api/bindings/{binding_id}/sync", files=_files(binding_id, key, bundle))
    assert r.status_code == 400
    await _assert_untouched(session, asset, fs_storage)


@pytest.mark.asyncio
async def test_sync_rejects_timestamp_beyond_clock_skew(client, session, fs_storage):
    asset, binding_id, key = await _new_binding(client, session)
    bundle = _make_tar_gz({"README.md": b"# v2\n"})
    ts = _iso(datetime.now(UTC) + timedelta(minutes=6))

    r = await client.post(
        f"/api/bindings/{binding_id}/sync", files=_files(binding_id, key, bundle, ts=ts)
    )
    assert r.status_code == 400
    await _assert_untouched(session, asset, fs_storage)


@pytest.mark.asyncio
async def test_sync_rejects_symlink_member(client, session, fs_storage):
    asset, binding_id, key = await _new_binding(client, session)
    bundle = _make_tar_gz({"README.md": b"# v2\n"}, force_links=True)

    r = await client.post(f"/api/bindings/{binding_id}/sync", files=_files(binding_id, key, bundle))
    assert r.status_code == 400
    await _assert_untouched(session, asset, fs_storage)


@pytest.mark.asyncio
async def test_sync_rejects_absolute_path_member(client, session, fs_storage):
    asset, binding_id, key = await _new_binding(client, session)
    bundle = _tar_with_absolute_member()

    r = await client.post(f"/api/bindings/{binding_id}/sync", files=_files(binding_id, key, bundle))
    assert r.status_code == 400
    await _assert_untouched(session, asset, fs_storage)


@pytest.mark.asyncio
async def test_sync_rejects_path_traversal_member(client, session, fs_storage):
    asset, binding_id, key = await _new_binding(client, session)
    bundle = _make_tar_gz({"README.md": b"# v2\n", "../escape.md": b"# out\n"})

    r = await client.post(f"/api/bindings/{binding_id}/sync", files=_files(binding_id, key, bundle))
    assert r.status_code == 400
    await _assert_untouched(session, asset, fs_storage)


@pytest.mark.asyncio
async def test_sync_rejects_bundle_not_matching_asset_kind(client, session, fs_storage):
    """An md_collection cannot be silently replaced with an HTML-only bundle."""
    asset, binding_id, key = await _new_binding(client, session)
    bundle = _make_tar_gz({"index.html": b"<html></html>"})

    r = await client.post(f"/api/bindings/{binding_id}/sync", files=_files(binding_id, key, bundle))
    assert r.status_code == 400
    await _assert_untouched(session, asset, fs_storage)


@pytest.mark.asyncio
async def test_sync_over_owner_quota_returns_413_and_cleans_storage(client, session, fs_storage):
    asset, binding_id, key = await _new_binding(client, session)
    owner = await session.get(User, asset.owner_id)
    owner.storage_quota_bytes = 10
    await session.commit()
    bundle = _make_tar_gz({"README.md": b"# " + b"x" * 200 + b"\n"})

    r = await client.post(f"/api/bindings/{binding_id}/sync", files=_files(binding_id, key, bundle))
    assert r.status_code == 413
    await _assert_untouched(session, asset, fs_storage)
