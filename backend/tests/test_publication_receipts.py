"""Publication retries exercise real HTTP routes, PostgreSQL and staged storage."""

import asyncio
import base64
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import get_session
from app.main import create_app
from app.models import Asset, AssetShare, AssetVersion, AuditLog, Project, ProjectMember, ShareLink
from app.routes.mcp_assets import upload
from app.services import asset_versions, publications
from tests.conftest import login_as, mk_user

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("fs_storage")]


def publication(**changes):
    return {"id": str(uuid4()), "order_id": "delivery-17", "role": "report", **changes}


def payload(key, **changes):
    return {
        "title": "Published report",
        "entry_path": "index.html",
        "files": [{"path": "index.html", "content_text": "<h1>Report</h1>"}],
        "publication": key,
        **changes,
    }


def receipt_url(key):
    return f"/api/assets/publications/{key['id']}"


def receipt_params(key, **changes):
    return {"order_id": key["order_id"], "role": key["role"], **changes}


@pytest_asyncio.fixture
async def http(session):
    # Real concurrent requests need distinct transactions, unlike the standard
    # client fixture which intentionally shares the test's session.
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


async def sign_in(session, http):
    user = await mk_user(session)
    await session.commit()
    await login_as(http, user)
    return user


async def asset_count(session, user):
    return await session.scalar(
        select(func.count()).select_from(Asset).where(Asset.owner_id == user.id)
    )


async def test_parallel_identical_publication_creates_one_asset(session, http, monkeypatch):
    user = await sign_in(session, http)
    key = publication()
    original = upload.stage_asset_files
    entered, release = asyncio.Event(), asyncio.Event()

    async def paused_stage(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(upload, "stage_asset_files", paused_stage)
    first = asyncio.create_task(http.post("/api/assets/html-json", json=payload(key)))
    await asyncio.wait_for(entered.wait(), 5)
    second = asyncio.create_task(http.post("/api/assets/html-json", json=payload(key)))
    # Both HTTP requests exist before the first storage transaction is released.
    await asyncio.sleep(0.05)
    release.set()
    a, b = await asyncio.wait_for(asyncio.gather(first, second), 10)
    assert (a.status_code, b.status_code) == (201, 201)
    assert a.json() == b.json()
    assert await asset_count(session, user) == 1
    asset_id = UUID(a.json()["id"])
    assert (
        await session.scalar(
            select(func.count()).select_from(AssetVersion).where(AssetVersion.asset_id == asset_id)
        )
        == 1
    )
    assert (
        await session.scalar(
            select(func.count()).select_from(ShareLink).where(ShareLink.asset_id == asset_id)
        )
        == 1
    )
    assert (
        await session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.target == f"asset:{asset_id}", AuditLog.action == "asset_uploaded")
        )
        == 1
    )


@pytest.mark.parametrize("lost_at", ["enqueue", "commit"])
async def test_lost_ack_receipt_is_durable_and_retry_skips_publication(
    session, http, monkeypatch, lost_at
):
    user = await sign_in(session, http)
    key = publication()

    async def lost_ack(*args, **kwargs):
        raise OSError("synthetic failure after commit")

    if lost_at == "enqueue":
        monkeypatch.setattr(upload, "enqueue", lost_ack)
    else:
        original = AsyncSession.commit

        async def committed_without_ack(current):
            await original(current)
            raise OSError("synthetic lost commit acknowledgement")

        monkeypatch.setattr(AsyncSession, "commit", committed_without_ack)
    first = await http.post("/api/assets/html-json", json=payload(key))
    assert first.status_code == 500
    found = await http.get(receipt_url(key), params=receipt_params(key))
    assert found.status_code == 200
    receipt = found.json()
    assert receipt["publication_id"] == key["id"]
    assert receipt["order_id"] == key["order_id"]
    assert receipt["role"] == "report"
    assert receipt["schema_version"] == 1
    assert receipt["version"] == 1
    assert len(receipt["payload_hash"]) == 64
    retried = await http.post("/api/assets/html-json", json=payload(key))
    assert retried.status_code == 201
    assert retried.json() == receipt["result"]
    assert await asset_count(session, user) == 1


async def test_same_scope_and_key_reject_changed_payload(session, http):
    user = await sign_in(session, http)
    key = publication()
    first = await http.post("/api/assets/html-json", json=payload(key))
    assert first.status_code == 201
    changed = await http.post("/api/assets/html-json", json=payload(key, title="Different intent"))
    assert changed.status_code == 409
    assert changed.json()["code"] == "publication_conflict"
    assert await asset_count(session, user) == 1


async def test_foreign_principal_cannot_read_receipt(session, http):
    owner = await sign_in(session, http)
    key = publication()
    assert (
        await http.post("/api/assets/html-json", json=payload(key, share_mode="public"))
    ).status_code == 201
    await sign_in(session, http)
    response = await http.get(receipt_url(key), params=receipt_params(key))
    assert response.status_code == 404
    assert response.json()["code"] == "publication_not_found"
    assert await asset_count(session, owner) == 1


async def test_equivalent_encodings_file_order_and_defaults_replay(session, http):
    user = await sign_in(session, http)
    key = publication()
    first_payload = payload(
        key,
        summary="  useful report  ",
        files=[
            {"path": "index.html", "content_text": "<h1>Report</h1>"},
            {"path": "style.css", "content_text": "h1 { color: red; }"},
        ],
    )
    first = await http.post("/api/assets/html-json", json=first_payload)
    assert first.status_code == 201
    second_payload = payload(
        key,
        summary="useful report",
        share_mode="org_sso",
        files=[
            {
                "path": row["path"],
                "content_base64": base64.b64encode(row["content_text"].encode()).decode(),
            }
            for row in reversed(first_payload["files"])
        ],
    )
    second = await http.post("/api/assets/html-json", json=second_payload)
    assert (second.status_code, second.json()) == (201, first.json())
    assert await asset_count(session, user) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"title": "other"},
        {"share_mode": "public"},
        {"tags": ["new-tag"]},
        {"summary": "new summary"},
        {"doc_type": "other-type"},
        {"files": [{"path": "index.html", "content_text": "other bytes"}]},
        {"files": [{"path": "index.html", "content_text": "<h1>Report</h1>", "mime": "text/html"}]},
    ],
)
async def test_semantic_payload_changes_conflict(session, http, change):
    user = await sign_in(session, http)
    key = publication()
    assert (await http.post("/api/assets/html-json", json=payload(key))).status_code == 201
    changed = await http.post("/api/assets/html-json", json=payload(key, **change))
    assert (changed.status_code, changed.json()["code"]) == (409, "publication_conflict")
    assert await asset_count(session, user) == 1


async def test_replay_does_not_consume_quota_again(session, http):
    user = await sign_in(session, http)
    user.storage_quota_bytes = 15
    await session.commit()
    key = publication()
    first = await http.post("/api/assets/html-json", json=payload(key))
    assert first.status_code == 201
    user.bundle_max_bytes = 1
    await session.commit()
    second = await http.post("/api/assets/html-json", json=payload(key))
    assert (second.status_code, second.json()) == (201, first.json())
    assert await asset_count(session, user) == 1


async def make_project(session, user):
    project = Project(slug=uuid4().hex, name="Publication project", created_by=user.id)
    session.add(project)
    await session.flush()
    member = ProjectMember(
        project_id=project.id, user_id=user.id, role="owner", accepted_at=datetime.now(UTC)
    )
    session.add(member)
    await session.commit()
    return project, member


async def test_scope_separates_order_role_project_and_principal(session, http):
    owner = await sign_in(session, http)
    project, _ = await make_project(session, owner)
    key = publication()
    requests = [
        payload(key),
        payload({**key, "order_id": "other-delivery"}),
        payload({**key, "role": "acceptance"}),
        payload(key, project_id=str(project.id)),
    ]
    results = [await http.post("/api/assets/html-json", json=value) for value in requests]
    assert [r.status_code for r in results] == [201] * 4
    assert len({r.json()["id"] for r in results}) == 4
    other = await sign_in(session, http)
    fifth = await http.post("/api/assets/html-json", json=payload(key))
    assert fifth.status_code == 201
    assert fifth.json()["id"] not in {r.json()["id"] for r in results}
    assert await asset_count(session, owner) == 4
    assert await asset_count(session, other) == 1


async def test_receipt_read_and_replay_check_current_project_membership(session, http):
    user = await sign_in(session, http)
    project, member = await make_project(session, user)
    key = publication()
    body = payload(key, project_id=str(project.id))
    assert (await http.post("/api/assets/html-json", json=body)).status_code == 201
    await session.delete(member)
    await session.commit()
    read = await http.get(receipt_url(key), params=receipt_params(key, project_id=str(project.id)))
    replay = await http.post("/api/assets/html-json", json=body)
    assert (read.status_code, replay.status_code) == (403, 403)
    assert await asset_count(session, user) == 1


@pytest.mark.parametrize("hard", [False, True])
async def test_removed_asset_consumes_key_without_recreation(session, http, hard):
    user = await sign_in(session, http)
    key = publication()
    first = await http.post("/api/assets/html-json", json=payload(key))
    asset = await session.get(Asset, UUID(first.json()["id"]))
    if hard:
        await session.delete(asset)
    else:
        asset.deleted_at = datetime.now(UTC)
    await session.commit()
    read = await http.get(receipt_url(key), params=receipt_params(key))
    retry = await http.post("/api/assets/html-json", json=payload(key))
    assert (read.status_code, retry.status_code) == (404, 404)
    assert await asset_count(session, user) == (0 if hard else 1)


async def test_failure_before_commit_leaves_no_receipt_and_retry_can_succeed(
    session, http, monkeypatch, fs_storage
):
    from pathlib import Path

    user = await sign_in(session, http)
    key = publication()

    async def fail_audit(*args, **kwargs):
        raise OSError("synthetic failure before commit")

    with monkeypatch.context() as patch:
        patch.setattr(upload.audit, "record_from_request", fail_audit)
        failed = await http.post("/api/assets/html-json", json=payload(key))
        assert failed.status_code == 500
    assert (await http.get(receipt_url(key), params=receipt_params(key))).status_code == 404
    assert await asset_count(session, user) == 0
    assert not [p for p in Path(fs_storage).rglob("*") if p.is_file()]
    retry = await http.post("/api/assets/html-json", json=payload(key))
    assert retry.status_code == 201
    assert await asset_count(session, user) == 1


@pytest.mark.parametrize(
    "field,value",
    [("id", "a/b"), ("id", ""), ("order_id", ""), ("role", "x\n"), ("principal_id", "spoofed")],
)
async def test_malformed_scope_refuses_before_creating_asset(session, http, field, value):
    user = await sign_in(session, http)
    response = await http.post("/api/assets/html-json", json=payload(publication(**{field: value})))
    assert response.status_code == 422
    assert await asset_count(session, user) == 0


async def test_legacy_request_without_publication_still_creates_each_time(session, http):
    user = await sign_in(session, http)
    body = payload(None)
    del body["publication"]
    a = await http.post("/api/assets/html-json", json=body)
    b = await http.post("/api/assets/html-json", json=body)
    assert (a.status_code, b.status_code) == (201, 201)
    assert a.json()["id"] != b.json()["id"]
    assert await asset_count(session, user) == 2


@pytest.mark.parametrize("revoke", ["membership", "project"])
async def test_new_publication_rechecks_project_after_waiting_for_scope_lock(
    session, http, revoke, fs_storage
):
    from pathlib import Path

    user = await sign_in(session, http)
    project, member = await make_project(session, user)
    key = publication()
    scope = publications.PublicationScope(
        user.id, project.id, key["order_id"], key["role"], key["id"]
    )
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    async with factory() as holder:
        assert await publications.lock_and_replay(holder, scope, user, "0" * 64) is None
        pid = await holder.scalar(text("SELECT pg_backend_pid()"))
        pending = asyncio.create_task(
            http.post("/api/assets/html-json", json=payload(key, project_id=str(project.id)))
        )

        async def wait_for_database_waiter():
            while not await session.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_locks waiting JOIN pg_locks held "
                    "USING (locktype, database, classid, objid, objsubid) "
                    "WHERE held.pid=:pid AND held.locktype='advisory' "
                    "AND held.granted AND NOT waiting.granted)"
                ),
                {"pid": pid},
            ):
                await asyncio.sleep(0.01)

        try:
            await asyncio.wait_for(wait_for_database_waiter(), 5)
            if revoke == "membership":
                await session.delete(member)
            else:
                project.deleted_at = datetime.now(UTC)
            await session.commit()
        finally:
            await holder.rollback()
        response = await asyncio.wait_for(pending, 5)

    assert response.status_code == (403 if revoke == "membership" else 404)
    assert await asset_count(session, user) == 0
    assert not [p for p in Path(fs_storage).rglob("*") if p.is_file()]


async def replace_publication(http, asset_id, key, *, expected=1, body=b"<h1>Next</h1>", **options):
    data = {"paths": "index.html", "publication": json.dumps(key), **options}
    if expected is not None:
        data["expected_version"] = str(expected)
    return await http.post(
        f"/api/assets/{asset_id}/versions",
        data=data,
        files={"files": ("index.html", body, "text/html")},
    )


async def versioned_asset(session, http, **options):
    user = await sign_in(session, http)
    created = await http.post("/api/assets/html-json", json=payload(None, **options))
    assert created.status_code == 201
    return user, UUID(created.json()["id"])


async def test_version_publication_lost_commit_ack_replays_original_result_after_later_version(
    session, http, monkeypatch
):
    _user, asset_id = await versioned_asset(session, http)
    key = publication()
    commit = AsyncSession.commit

    async def lost_ack(current):
        await commit(current)
        raise OSError("synthetic lost acknowledgement after the real version commit")

    with monkeypatch.context() as fault:
        fault.setattr(AsyncSession, "commit", lost_ack)
        first = await replace_publication(http, asset_id, key)
    assert first.status_code == 500
    found = await http.get(receipt_url(key), params=receipt_params(key))
    assert found.status_code == 200
    original = found.json()["result"]
    assert found.json()["version"] == original["version"] == 2
    repeated = await replace_publication(http, asset_id, key)
    assert (repeated.status_code, repeated.json()) == (201, original)
    newer = await replace_publication(
        http, asset_id, publication(), expected=2, body=b"<h1>Third</h1>"
    )
    assert newer.status_code == 201
    assert newer.json()["version"] == 3
    repeated = await replace_publication(http, asset_id, key)
    assert (repeated.status_code, repeated.json()) == (201, original)
    assert await session.scalar(select(Asset.version).where(Asset.id == asset_id)) == 3
    assert (
        await session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.target == f"asset:{asset_id}", AuditLog.action == "asset_versioned")
        )
        == 2
    )


async def test_parallel_version_publication_waits_and_stages_once(session, http, monkeypatch):
    _user, asset_id = await versioned_asset(session, http)
    key = publication()
    entered, release = asyncio.Event(), asyncio.Event()
    write = asset_versions.write_uploads
    staged = 0
    holder_pids = []
    lock = publications.lock_and_replay

    async def observed_lock(current, *args, **kwargs):
        holder_pids.append(await current.scalar(text("SELECT pg_backend_pid()")))
        return await lock(current, *args, **kwargs)

    monkeypatch.setattr(publications, "lock_and_replay", observed_lock)

    def paused_uploads(*args, **kwargs):
        stage = write(*args, **kwargs)

        async def paused(draft):
            nonlocal staged
            staged += 1
            entered.set()
            await release.wait()
            return await stage(draft)

        return paused

    monkeypatch.setattr(asset_versions, "write_uploads", paused_uploads)
    first = asyncio.create_task(replace_publication(http, asset_id, key))
    await asyncio.wait_for(entered.wait(), 5)
    second = asyncio.create_task(replace_publication(http, asset_id, key))

    async def waiter():
        while not await session.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM pg_locks waiting JOIN pg_locks held "
                "USING (locktype, database, classid, objid, objsubid) "
                "WHERE held.pid=:pid AND held.locktype='advisory' "
                "AND held.granted AND NOT waiting.granted)"
            ),
            {"pid": holder_pids[0]},
        ):
            await asyncio.sleep(0.01)

    try:
        await asyncio.wait_for(waiter(), 5)
    finally:
        release.set()
    a, b = await asyncio.wait_for(asyncio.gather(first, second), 10)
    assert (a.status_code, b.status_code) == (201, 201)
    assert a.json() == b.json()
    assert staged == 1
    assert await session.scalar(select(Asset.version).where(Asset.id == asset_id)) == 2


@pytest.mark.parametrize("change", ["body", "expected", "change_note", "asset"])
async def test_version_publication_rejects_changed_intent(session, http, change):
    _user, asset_id = await versioned_asset(session, http)
    key = publication()
    first = await replace_publication(http, asset_id, key)
    assert first.status_code == 201
    options = {}
    if change == "body":
        options["body"] = b"<h1>Different</h1>"
    elif change == "expected":
        options["expected"] = 2
    elif change == "change_note":
        options["change_note"] = "A different publication"
    else:
        other = await http.post("/api/assets/html-json", json=payload(None))
        assert other.status_code == 201
        asset_id = UUID(other.json()["id"])
    changed = await replace_publication(http, asset_id, key, **options)
    assert changed.status_code == 409
    assert changed.json()["code"] == "publication_conflict"


async def test_new_publication_key_requires_current_expected_version(session, http):
    _user, asset_id = await versioned_asset(session, http)
    assert (await replace_publication(http, asset_id, publication())).status_code == 201
    stale = await replace_publication(http, asset_id, publication())
    assert stale.status_code == 409
    assert stale.json()["code"] == "version_conflict"
    missing = await replace_publication(http, asset_id, publication(), expected=None)
    assert missing.status_code == 422
    assert missing.json()["code"] == "validation_error"
    assert await session.scalar(select(Asset.version).where(Asset.id == asset_id)) == 2


@pytest.mark.parametrize("failure", ["stage", "before_commit"])
async def test_version_receipt_and_version_are_absent_when_transaction_fails(
    session, http, monkeypatch, failure
):
    _user, asset_id = await versioned_asset(session, http)
    key = publication()
    with monkeypatch.context() as fault:
        if failure == "stage":
            original = asset_versions.write_uploads

            def partial(*args, **kwargs):
                stage = original(*args, **kwargs)

                async def write_then_fail(draft):
                    await stage(draft)
                    raise OSError("synthetic failure after writing the staged tree")

                return write_then_fail

            fault.setattr(asset_versions, "write_uploads", partial)
        else:

            async def fail_commit(current):
                await current.flush()
                raise OSError("synthetic failure before COMMIT")

            fault.setattr(AsyncSession, "commit", fail_commit)
        failed = await replace_publication(http, asset_id, key)
    assert failed.status_code == 500
    assert (await http.get(receipt_url(key), params=receipt_params(key))).status_code == 404
    assert await session.scalar(select(Asset.version).where(Asset.id == asset_id)) == 1
    assert (
        await session.scalar(
            select(func.count()).select_from(AssetVersion).where(AssetVersion.asset_id == asset_id)
        )
        == 1
    )
    retried = await replace_publication(http, asset_id, key)
    assert retried.status_code == 201
    assert retried.json()["version"] == 2
    receipt = await http.get(receipt_url(key), params=receipt_params(key))
    assert receipt.status_code == 200
    assert receipt.json()["result"] == retried.json()


@pytest.mark.parametrize("replay", [False, True])
async def test_version_publication_rechecks_deleted_asset_after_advisory_wait(
    session, http, replay
):
    user, asset_id = await versioned_asset(session, http)
    key = publication()
    if replay:
        assert (await replace_publication(http, asset_id, key)).status_code == 201
    scope = publications.PublicationScope(user.id, None, key["order_id"], key["role"], key["id"])
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    async with factory() as holder:
        if not replay:
            await publications.lock_and_replay(holder, scope, user, "not-used-for-lock")
        else:
            receipt = await publications.find_receipt(holder, scope)
            assert receipt is not None
            await publications.lock_and_replay(holder, scope, user, receipt.payload_hash)
        pid = await holder.scalar(text("SELECT pg_backend_pid()"))
        pending = asyncio.create_task(replace_publication(http, asset_id, key))

        async def waiter():
            while not await session.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_locks waiting JOIN pg_locks held "
                    "USING (locktype, database, classid, objid, objsubid) "
                    "WHERE held.pid=:pid AND held.locktype='advisory' "
                    "AND held.granted AND NOT waiting.granted)"
                ),
                {"pid": pid},
            ):
                await asyncio.sleep(0.01)

        try:
            await asyncio.wait_for(waiter(), 5)
            asset = await session.get(Asset, asset_id)
            asset.deleted_at = datetime.now(UTC)
            await session.commit()
        finally:
            await holder.rollback()
        response = await asyncio.wait_for(pending, 5)
    assert response.status_code == 404
    assert (await http.get(receipt_url(key), params=receipt_params(key))).status_code == 404
    assert await session.scalar(select(Asset.version).where(Asset.id == asset_id)) == (
        2 if replay else 1
    )


@pytest.mark.parametrize(
    "key",
    [
        {"id": "white space", "order_id": "o", "role": "r"},
        {"id": "id", "order_id": "o", "role": "r", "unexpected": True},
        "broken-json",
    ],
)
async def test_version_publication_key_shape_is_validated(session, http, key):
    _user, asset_id = await versioned_asset(session, http)
    response = await replace_publication(http, asset_id, key)
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert await session.scalar(select(Asset.version).where(Asset.id == asset_id)) == 1


async def test_version_publication_hash_normalizes_files_and_effective_options(session, http):
    _user, asset_id = await versioned_asset(session, http)
    key = publication()
    files = [("index.html", b"<h1>Index</h1>"), ("other.html", b"<h1>Other</h1>")]

    async def publish(rows, **changes):
        return await http.post(
            f"/api/assets/{asset_id}/versions",
            data={
                "paths": [path for path, _ in rows],
                "publication": json.dumps(key),
                "expected_version": "1",
                "change_note": "note",
                **changes,
            },
            files=[("files", (path, body, "text/html")) for path, body in rows],
        )

    first = await publish(files, change_note="  note \n")
    assert first.status_code == 201
    equivalent = await publish(list(reversed(files)), entry_path="index.html")
    assert (equivalent.status_code, equivalent.json()) == (201, first.json())
    changed = await publish(files, entry_path="other.html")
    assert changed.status_code == 409
    assert changed.json()["code"] == "publication_conflict"


async def test_version_publication_rejects_duplicate_normalized_paths(session, http):
    _user, asset_id = await versioned_asset(session, http)
    response = await http.post(
        f"/api/assets/{asset_id}/versions",
        data={
            "paths": ["index.html", "index.html"],
            "publication": json.dumps(publication()),
            "expected_version": "1",
        },
        files=[("files", ("index.html", b"<h1>A</h1>")), ("files", ("index.html", b"<h1>B</h1>"))],
    )
    assert response.status_code == 400
    assert response.json()["code"] == "duplicate_path"
    assert await session.scalar(select(Asset.version).where(Asset.id == asset_id)) == 1


async def test_creation_key_cannot_be_reused_for_next_version(session, http):
    await sign_in(session, http)
    key = publication()
    created = await http.post("/api/assets/html-json", json=payload(key))
    assert created.status_code == 201
    response = await replace_publication(http, created.json()["id"], key)
    assert response.status_code == 409
    assert response.json()["code"] == "publication_conflict"


@pytest.mark.parametrize("replay", [False, True])
async def test_version_publication_rechecks_editor_downgrade_after_wait(session, http, replay):
    _owner, asset_id = await versioned_asset(session, http)
    editor = await mk_user(session)
    share = AssetShare(asset_id=asset_id, user_id=editor.id, role="editor")
    session.add(share)
    await session.commit()
    await login_as(http, editor)
    key = publication()
    if replay:
        assert (await replace_publication(http, asset_id, key)).status_code == 201
    scope = publications.PublicationScope(editor.id, None, key["order_id"], key["role"], key["id"])
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    async with factory() as holder:
        existing = await publications.find_receipt(holder, scope)
        await publications.lock_and_replay(
            holder, scope, editor, existing.payload_hash if existing else "new"
        )
        pid = await holder.scalar(text("SELECT pg_backend_pid()"))
        pending = asyncio.create_task(replace_publication(http, asset_id, key))

        async def waiter():
            while not await session.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_locks waiting JOIN pg_locks held "
                    "USING (locktype, database, classid, objid, objsubid) "
                    "WHERE held.pid=:pid AND held.locktype='advisory' "
                    "AND held.granted AND NOT waiting.granted)"
                ),
                {"pid": pid},
            ):
                await asyncio.sleep(0.01)

        try:
            await asyncio.wait_for(waiter(), 5)
            share.role = "viewer"
            await session.commit()
        finally:
            await holder.rollback()
        response = await asyncio.wait_for(pending, 5)
    assert response.status_code == 404
    assert await session.scalar(select(Asset.version).where(Asset.id == asset_id)) == (
        2 if replay else 1
    )
    # A viewer can still read an already committed receipt, but cannot mutate.
    found = await http.get(receipt_url(key), params=receipt_params(key))
    assert found.status_code == (200 if replay else 404)
