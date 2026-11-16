"""Publication retries exercise real HTTP routes, PostgreSQL and staged storage."""

import asyncio
import base64
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import get_session
from app.main import create_app
from app.models import Asset, AssetVersion, AuditLog, Project, ProjectMember, ShareLink
from app.routes.mcp_assets import upload
from app.services import publications
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
