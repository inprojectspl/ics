"""Signed release identity uses real HTTP routes and PostgreSQL transactions."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import signing
from app.db import get_session
from app.main import create_app
from app.models import AssetVersion, AuditLog, GitLabBinding, Project, PublicationReceipt, User
from app.services import asset_versions, notifications
from tests.conftest import login_as, make_tar_gz, mk_asset, mk_user

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("fs_storage")]


@pytest_asyncio.fixture
async def http(session):
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    app = create_app()

    async def sessions():
        async with factory() as current:
            yield current

    app.dependency_overrides[get_session] = sessions
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://testserver"
    ) as client:
        yield client


async def new_binding(session, http, *, in_project=False):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner, kind="md_collection", entry_path="README.md")
    if in_project:
        project = Project(slug=uuid4().hex, name="Synthetic release project", created_by=owner.id)
        session.add(project)
        await session.flush()
        asset.project_id = project.id
    await session.commit()
    await login_as(http, owner)
    response = await http.post("/api/bindings", json={"asset_id": str(asset.id)})
    assert response.status_code == 201, response.text
    await http.post("/api/auth/logout")
    return asset, response.json()["id"], response.json()["private_key"]


def manifest(binding_id, bundle, **changes):
    return {
        "binding_id": binding_id,
        "commit_sha": "a" * 40,
        "commit_timestamp": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        "bundle_sha256": hashlib.sha256(bundle).hexdigest(),
        "release_id": str(uuid4()),
        "release_generation": 1,
        **changes,
    }


def signed_files(body, key, bundle):
    data = json.dumps(body).encode()
    return {
        "manifest": ("manifest.json", data, "application/json"),
        "signature": ("signature.b64", signing.sign(data, key).encode(), "text/plain"),
        "bundle": ("bundle.tar.gz", bundle, "application/gzip"),
    }


async def post(http, binding_id, body, key, bundle):
    return await http.post(
        f"/api/bindings/{binding_id}/sync", files=signed_files(body, key, bundle)
    )


async def version_count(session, asset):
    return await session.scalar(
        select(func.count()).select_from(AssetVersion).where(AssetVersion.asset_id == asset.id)
    )


@pytest.mark.parametrize("lost_at", ["commit", "notification"])
async def test_signed_release_recovers_receipt_after_lost_ack(session, http, monkeypatch, lost_at):
    asset, binding_id, key = await new_binding(session, http)
    bundle = make_tar_gz({"README.md": b"# Release\n"})
    body = manifest(binding_id, bundle)
    original_commit = AsyncSession.commit

    async def lost_ack(*args, **kwargs):
        if lost_at == "commit":
            await original_commit(*args, **kwargs)
        raise OSError("synthetic lost acknowledgement after commit")

    with monkeypatch.context() as fault:
        if lost_at == "commit":
            fault.setattr(AsyncSession, "commit", lost_ack)
        else:
            fault.setattr(notifications, "dispatch_sync_notification", lost_ack)
        failed = await post(http, binding_id, body, key, bundle)
    assert failed.status_code == 500
    assert await version_count(session, asset) == 1
    binding = await session.get(GitLabBinding, UUID(binding_id), populate_existing=True)
    assert binding.last_release_generation == 1

    retried = await post(http, binding_id, body, key, bundle)
    assert retried.status_code == 201, retried.text
    assert retried.json()["version"] == 2
    receipt = retried.json()["receipt"]
    assert receipt["binding_id"] == binding_id
    assert receipt["release_id"] == body["release_id"]
    assert receipt["release_generation"] == 1
    assert len(receipt["payload_hash"]) == 64
    stored = await session.get(PublicationReceipt, UUID(receipt["id"]))
    assert stored is not None
    assert stored.result == retried.json()
    assert await version_count(session, asset) == 1
    repeated = await post(http, binding_id, body, key, bundle)
    assert repeated.status_code == 201
    assert repeated.json() == retried.json()
    assert (
        await session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.target == f"asset:{asset.id}", AuditLog.action == "binding_synced")
        )
        == 1
    )


@pytest.mark.parametrize("older_timestamp", [False, True])
async def test_generation_orders_releases_and_historical_replay_does_not_rewind(
    session, http, older_timestamp
):
    asset, binding_id, key = await new_binding(session, http)
    bundle = make_tar_gz({"README.md": b"# First release\n"})
    first_body = manifest(binding_id, bundle, release_generation=8)
    first = await post(http, binding_id, first_body, key, bundle)
    assert first.status_code == 201
    newer_bundle = make_tar_gz({"README.md": b"# Next release\n"})
    newer_body = manifest(
        binding_id,
        newer_bundle,
        release_generation=9,
        commit_timestamp=(
            (datetime.fromisoformat(first_body["commit_timestamp"]) - timedelta(days=1)).isoformat()
            if older_timestamp
            else first_body["commit_timestamp"]
        ),
        commit_sha="b" * 40,
    )
    newer = await post(http, binding_id, newer_body, key, newer_bundle)
    assert newer.status_code == 201, newer.text
    assert newer.json()["version"] == 3
    historical = await post(http, binding_id, first_body, key, bundle)
    assert historical.status_code == 201, historical.text
    assert historical.json() == first.json()
    await session.refresh(asset)
    binding = await session.get(GitLabBinding, UUID(binding_id), populate_existing=True)
    assert asset.version == 3
    assert binding.last_release_generation == 9
    assert binding.last_sync_commit_sha == newer_body["commit_sha"]
    assert await version_count(session, asset) == 2


async def test_legacy_manifest_cannot_bypass_adopted_generation(session, http):
    asset, binding_id, key = await new_binding(session, http)
    bundle = make_tar_gz({"README.md": b"# Release\n"})
    body = manifest(binding_id, bundle, release_generation=7)
    assert (await post(http, binding_id, body, key, bundle)).status_code == 201
    legacy = dict(body, commit_timestamp=datetime.now(UTC).isoformat())
    del legacy["release_id"], legacy["release_generation"]
    denied = await post(http, binding_id, legacy, key, bundle)
    assert (denied.status_code, denied.json().get("code")) == (409, "release_required")
    assert await version_count(session, asset) == 1


@pytest.mark.parametrize("changed", ["commit", "bundle", "generation", "timestamp"])
async def test_consumed_release_id_rejects_another_intent(session, http, changed):
    asset, binding_id, key = await new_binding(session, http)
    bundle = make_tar_gz({"README.md": b"# Release\n"})
    body = manifest(binding_id, bundle)
    assert (await post(http, binding_id, body, key, bundle)).status_code == 201
    different = dict(body)
    if changed == "commit":
        different["commit_sha"] = "b" * 40
    elif changed == "bundle":
        bundle = make_tar_gz({"README.md": b"# Different release\n"})
        different["bundle_sha256"] = hashlib.sha256(bundle).hexdigest()
    elif changed == "generation":
        different["release_generation"] = 2
    else:
        different["commit_timestamp"] = datetime.now(UTC).isoformat()
    denied = await post(http, binding_id, different, key, bundle)
    assert (denied.status_code, denied.json().get("code")) == (409, "publication_conflict")
    assert await version_count(session, asset) == 1


@pytest.mark.parametrize("generation", [3, 4])
async def test_new_id_cannot_reuse_or_decrease_generation(session, http, generation):
    asset, binding_id, key = await new_binding(session, http)
    bundle = make_tar_gz({"README.md": b"# Release\n"})
    first = manifest(binding_id, bundle, release_generation=4)
    assert (await post(http, binding_id, first, key, bundle)).status_code == 201
    other = manifest(
        binding_id,
        bundle,
        release_generation=generation,
        commit_timestamp=datetime.now(UTC).isoformat(),
    )
    denied = await post(http, binding_id, other, key, bundle)
    assert (denied.status_code, denied.json().get("code")) == (409, "release_generation_conflict")
    assert await version_count(session, asset) == 1


@pytest.mark.parametrize("invalid", [0, -1, True, 1.5, "2", None])
async def test_generation_validation_cannot_fall_back_to_legacy(session, http, invalid):
    asset, binding_id, key = await new_binding(session, http)
    bundle = make_tar_gz({"README.md": b"# Release\n"})
    body = manifest(binding_id, bundle, release_generation=invalid)
    response = await post(http, binding_id, body, key, bundle)
    assert (response.status_code, response.json().get("code")) == (400, "manifest_invalid")
    assert await version_count(session, asset) == 0


@pytest.mark.parametrize("invalid", ["signature", "hash", "time"])
async def test_receipt_does_not_bypass_signed_request_validation(session, http, invalid):
    asset, binding_id, key = await new_binding(session, http)
    bundle = make_tar_gz({"README.md": b"# Release\n"})
    body = manifest(binding_id, bundle)
    assert (await post(http, binding_id, body, key, bundle)).status_code == 201
    expected = (403, "bad_signature")
    if invalid == "signature":
        key, _public = signing.generate_keypair()
    elif invalid == "hash":
        bundle = b"different bytes under the original signed hash"
        expected = (400, "bundle_hash_mismatch")
    else:
        body["commit_timestamp"] = (datetime.now(UTC) + timedelta(minutes=6)).isoformat()
        expected = (400, "commit_from_future")
    denied = await post(http, binding_id, body, key, bundle)
    assert (denied.status_code, denied.json().get("code")) == expected
    assert await version_count(session, asset) == 1


async def test_concurrent_identical_releases_stage_once(session, http, monkeypatch):
    from starlette.datastructures import UploadFile

    asset, binding_id, key = await new_binding(session, http)
    bundle = make_tar_gz({"README.md": b"# Release\n"})
    body = manifest(binding_id, bundle)
    entered, release, second_upload = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original_stage, original_read = asset_versions.extract_to_storage, UploadFile.read
    stages, uploads = [], []

    async def stage(**kwargs):
        stages.append(True)
        entered.set()
        await release.wait()
        return await original_stage(**kwargs)

    async def read(file, *args, **kwargs):
        if file.filename == "bundle.tar.gz":
            uploads.append(file)
            if len(uploads) == 2:
                second_upload.set()
        return await original_read(file, *args, **kwargs)

    monkeypatch.setattr(asset_versions, "extract_to_storage", stage)
    monkeypatch.setattr(UploadFile, "read", read)
    first = asyncio.create_task(post(http, binding_id, body, key, bundle))
    await asyncio.wait_for(entered.wait(), 5)
    second = asyncio.create_task(post(http, binding_id, body, key, bundle))
    await asyncio.wait_for(second_upload.wait(), 5)
    release.set()
    a, b = await asyncio.wait_for(asyncio.gather(first, second), 10)
    assert (a.status_code, b.status_code) == (201, 201)
    assert a.json() == b.json()
    assert len(stages) == 1
    assert await version_count(session, asset) == 1


async def test_failure_before_commit_does_not_consume_release_or_generation(
    session, http, monkeypatch
):
    asset, binding_id, key = await new_binding(session, http)
    bundle = make_tar_gz({"README.md": b"# Release\n"})
    body = manifest(binding_id, bundle)

    async def fail_before_commit(current):
        raise OSError("synthetic failure before commit")

    with monkeypatch.context() as fault:
        fault.setattr(AsyncSession, "commit", fail_before_commit)
        failed = await post(http, binding_id, body, key, bundle)
    assert failed.status_code == 500
    assert await version_count(session, asset) == 0
    binding = await session.get(GitLabBinding, UUID(binding_id), populate_existing=True)
    assert binding.last_release_generation is None
    assert (
        await session.scalar(
            select(func.count())
            .select_from(PublicationReceipt)
            .where(PublicationReceipt.asset_id == asset.id)
        )
        == 0
    )
    retried = await post(http, binding_id, body, key, bundle)
    assert retried.status_code == 201, retried.text
    assert retried.json()["version"] == 2
    assert retried.json()["receipt"]["release_generation"] == 1


@pytest.mark.parametrize("release_id", [None, "", "space forbidden", "x" * 201])
async def test_release_identity_validation_does_not_publish(session, http, release_id):
    asset, binding_id, key = await new_binding(session, http)
    bundle = make_tar_gz({"README.md": b"# Release\n"})
    body = manifest(binding_id, bundle, release_id=release_id)
    response = await post(http, binding_id, body, key, bundle)
    assert (response.status_code, response.json().get("code")) == (400, "manifest_invalid")
    assert await version_count(session, asset) == 0


async def test_same_release_id_isolated_by_binding_and_project(session, http):
    first_asset, first_id, first_key = await new_binding(session, http, in_project=True)
    second_asset, second_id, second_key = await new_binding(session, http, in_project=True)
    assert first_asset.project_id != second_asset.project_id
    bundle = make_tar_gz({"README.md": b"# Release\n"})
    first_body = manifest(first_id, bundle)
    second_body = dict(first_body, binding_id=second_id)
    first = await post(http, first_id, first_body, first_key, bundle)
    second = await post(http, second_id, second_body, second_key, bundle)
    assert (first.status_code, second.status_code) == (201, 201)
    assert first.json()["receipt"]["id"] != second.json()["receipt"]["id"]
    for asset, response in [(first_asset, first), (second_asset, second)]:
        receipt = await session.get(PublicationReceipt, UUID(response.json()["receipt"]["id"]))
        assert receipt.asset_id == asset.id
        assert receipt.project_id == asset.project_id
        assert receipt.principal_id is None
        assert await version_count(session, asset) == 1
    owner = await session.get(User, first_asset.owner_id)
    await login_as(http, owner)
    user_read = await http.get(
        f"/api/assets/publications/{first_body['release_id']}",
        params={
            "project_id": str(first_asset.project_id),
            "order_id": first_id,
            "role": "binding_sync",
        },
    )
    assert (user_read.status_code, user_read.json()["code"]) == (404, "publication_not_found")


async def test_legacy_upload_rechecks_generation_adopted_while_waiting(session, http, monkeypatch):
    from starlette.datastructures import UploadFile

    asset, binding_id, key = await new_binding(session, http)
    bundle = make_tar_gz({"README.md": b"# Release\n"})
    body = manifest(binding_id, bundle)
    legacy = dict(body, commit_timestamp=datetime.now(UTC).isoformat())
    del legacy["release_id"], legacy["release_generation"]
    entered, release = asyncio.Event(), asyncio.Event()
    original = UploadFile.read

    async def read(file, *args, **kwargs):
        if file.filename == "bundle.tar.gz" and not entered.is_set():
            entered.set()
            await release.wait()
        return await original(file, *args, **kwargs)

    monkeypatch.setattr(UploadFile, "read", read)
    pending = asyncio.create_task(post(http, binding_id, legacy, key, bundle))
    await asyncio.wait_for(entered.wait(), 5)
    adopted = await post(http, binding_id, body, key, bundle)
    assert adopted.status_code == 201
    release.set()
    denied = await asyncio.wait_for(pending, 5)
    assert (denied.status_code, denied.json()["code"]) == (409, "release_required")
    assert await version_count(session, asset) == 1


async def test_key_rotation_during_upload_revokes_the_pending_signature(session, http, monkeypatch):
    from starlette.datastructures import UploadFile

    asset, binding_id, key = await new_binding(session, http)
    bundle = make_tar_gz({"README.md": b"# Release\n"})
    body = manifest(binding_id, bundle)
    entered, release = asyncio.Event(), asyncio.Event()
    original = UploadFile.read

    async def read(file, *args, **kwargs):
        if file.filename == "bundle.tar.gz":
            entered.set()
            await release.wait()
        return await original(file, *args, **kwargs)

    monkeypatch.setattr(UploadFile, "read", read)
    pending = asyncio.create_task(post(http, binding_id, body, key, bundle))
    await asyncio.wait_for(entered.wait(), 5)
    binding = await session.get(GitLabBinding, UUID(binding_id))
    _private, binding.public_key = signing.generate_keypair()
    await session.commit()
    release.set()
    denied = await asyncio.wait_for(pending, 5)
    assert (denied.status_code, denied.json()["code"]) == (403, "bad_signature")
    assert await version_count(session, asset) == 0
