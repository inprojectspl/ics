"""OCR runs (ADR-0021): automatic queueing on a write, the request and retry
endpoint, the state in every read an agent or the viewer makes, the job
from queued to done or failed, and the sweeper.

The engine is a fake provider registered in `PROVIDERS`, so the lifecycle is
tested without the model; `test_ocr_engine.py` covers the engine."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings, get_settings
from app.jobs import queue as queue_mod
from app.models import Asset, DocumentOcr
from app.services import documents
from app.services.ocr import providers, runs
from app.services.ocr.providers import OcrFailure, PageCallback
from app.storage import storage_from_url
from app.util import now as utc_now
from tests.conftest import login_as, mk_md_single, mk_user
from tests.pdf_factory import make_pdf, pdf_file


class FakeProvider:
    name = "fake"
    needs_api_key = False
    markdown = False

    def __init__(self) -> None:
        self.texts: dict[int, str] = {}
        self.fail: str | None = None
        self.calls: list[list[int]] = []

    async def recognize(
        self,
        pdf: bytes,
        pages: Sequence[int],
        settings: Settings,
        on_page: PageCallback,
        *,
        api_key: str | None = None,
    ) -> str:
        self.calls.append(list(pages))
        if self.fail:
            raise OcrFailure(self.fail)
        for number in pages:
            await on_page(number, self.texts.get(number, f"scanned words page {number}"))
        return "fake 1.0"


@pytest.fixture
def ocr_env(monkeypatch, session, fs_storage):
    fake = FakeProvider()
    monkeypatch.setitem(providers.PROVIDERS, "fake", fake)
    monkeypatch.setattr(get_settings(), "ocr_provider", "fake")
    monkeypatch.setattr(get_settings(), "ocr_providers", ["fake"])
    pool = MagicMock()
    pool.enqueue_job = AsyncMock()
    monkeypatch.setattr(queue_mod, "get_pool", AsyncMock(return_value=pool))
    return fake, pool, async_sessionmaker(session.bind, expire_on_commit=False)


async def _owner(client, session):
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)
    return user


async def _upload(client, pages):
    r = await client.post("/api/assets/pdf", files=pdf_file("scan.pdf", make_pdf(pages)))
    assert r.status_code == 201, r.text
    return r.json()


async def _ocr(client, slug):
    r = await client.get(f"/api/assets/by-slug/{slug}/ocr")
    assert r.status_code == 200, r.text
    return r.json()["ocr"]


def _ocr_jobs(pool) -> list:
    return [c for c in pool.enqueue_job.await_args_list if c.args[0] == "ocr_document"]


@pytest.mark.asyncio
async def test_scan_upload_queues_ocr_and_the_run_puts_text_everywhere(client, session, ocr_env):
    fake, pool, factory = ocr_env
    await _owner(client, session)
    body = await _upload(client, ["Cover page", None, None])
    assert body["ocr"]["status"] == "queued"
    assert body["ocr"]["pages_without_text"] == 2
    [job] = _ocr_jobs(pool)
    assert job.args[1:] == (body["id"], 1)
    assert job.kwargs["_queue_name"] == get_settings().ocr_queue_name

    before = await client.get(f"/api/assets/by-slug/{body['slug']}/meta")
    fake.texts = {2: "Crème brûlée à la carte", 3: ""}
    result = await runs.run(factory, _uuid(body["id"]), 1, get_settings())
    assert result["found"] == 1
    assert fake.calls == [[2, 3]]

    state = await _ocr(client, body["slug"])
    assert state["status"] == "done"
    assert (state["pages_total"], state["pages_done"], state["pages_recognized"]) == (2, 2, 1)
    assert state["provider"] == "fake" and state["finished_at"] and state["error_code"] is None

    read = (await client.get(f"/api/assets/by-slug/{body['slug']}/file-mcp")).json()
    assert "_Text recognized by OCR._\n\nCrème brûlée à la carte" in read["content"]
    assert "OCR found no text" in read["content"]
    assert read["text_page_count"] == 1 and read["ocr_page_count"] == 1
    assert read["ocr"]["status"] == "done"

    hits = await client.get("/api/assets/search-mcp?q=brûlée")
    assert [h["slug"] for h in hits.json()["items"]] == [body["slug"]]
    # The run moves on without a new version: the meta ETag must follow it.
    after = await client.get(
        f"/api/assets/by-slug/{body['slug']}/meta",
        headers={"If-None-Match": before.headers["etag"]},
    )
    assert after.status_code == 200
    assert after.json()["ocr"]["status"] == "done"


def _uuid(value: str):
    from uuid import UUID

    return UUID(value)


@pytest.mark.asyncio
async def test_text_pdf_needs_no_ocr(client, session, ocr_env):
    _, pool, _ = ocr_env
    user = await _owner(client, session)
    body = await _upload(client, ["All text"])
    assert body["ocr"]["status"] == "not_requested"
    assert body["ocr"]["pages_without_text"] == 0
    assert _ocr_jobs(pool) == []
    r = await client.post(f"/api/assets/{body['id']}/ocr")
    assert r.status_code == 409
    assert r.json()["code"] == "ocr_not_needed"
    assert user is not None


@pytest.mark.asyncio
async def test_text_formats_have_no_ocr(client, session, ocr_env):
    _, asset = await mk_md_single(client, session)
    r = await client.post(f"/api/assets/{asset.id}/ocr")
    assert r.status_code == 400 and r.json()["code"] == "ocr_not_supported"
    r = await client.get(f"/api/assets/by-slug/{asset.slug}/ocr")
    assert r.status_code == 400 and r.json()["code"] == "ocr_not_supported"
    meta = (await client.get(f"/api/assets/by-slug/{asset.slug}/meta")).json()
    assert meta["ocr"] is None


@pytest.mark.asyncio
async def test_failed_run_can_be_retried_but_not_while_active(client, session, ocr_env):
    fake, pool, factory = ocr_env
    await _owner(client, session)
    body = await _upload(client, [None])
    r = await client.post(f"/api/assets/{body['id']}/ocr")
    assert r.status_code == 409 and r.json()["code"] == "ocr_in_progress"

    fake.fail = "ocr_engine_failed"
    await runs.run(factory, _uuid(body["id"]), 1, get_settings())
    state = await _ocr(client, body["slug"])
    assert (state["status"], state["error_code"]) == ("failed", "ocr_engine_failed")
    assert state["finished_at"] is not None

    fake.fail = None
    r = await client.post(f"/api/assets/{body['id']}/ocr")
    assert r.status_code == 202, r.text
    retry = r.json()["ocr"]
    assert retry["status"] == "queued" and retry["error_code"] is None
    first, second = _ocr_jobs(pool)
    assert first.kwargs["_job_id"] != second.kwargs["_job_id"]
    await runs.run(factory, _uuid(body["id"]), 1, get_settings())
    assert (await _ocr(client, body["slug"]))["status"] == "done"

    # A finished run can be repeated too (a poor result, a better engine).
    r = await client.post(f"/api/assets/{body['id']}/ocr")
    assert r.status_code == 202


@pytest.mark.asyncio
async def test_a_second_job_for_the_same_run_does_nothing(client, session, ocr_env):
    fake, _, factory = ocr_env
    await _owner(client, session)
    body = await _upload(client, [None])
    await runs.run(factory, _uuid(body["id"]), 1, get_settings())
    again = await runs.run(factory, _uuid(body["id"]), 1, get_settings())
    assert again["skipped"] == "not_queued"
    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_run_over_the_time_budget_fails_with_timeout(client, session, ocr_env, monkeypatch):
    fake, _, factory = ocr_env
    await _owner(client, session)
    body = await _upload(client, [None])

    async def slow(*args, **kwargs):
        import asyncio

        await asyncio.sleep(5)
        return "fake"

    monkeypatch.setattr(fake, "recognize", slow)
    monkeypatch.setattr(get_settings(), "ocr_timeout_seconds", 0.2)
    await runs.run(factory, _uuid(body["id"]), 1, get_settings())
    state = await _ocr(client, body["slug"])
    assert (state["status"], state["error_code"]) == ("failed", "ocr_timeout")


@pytest.mark.asyncio
async def test_lost_derived_files_are_rebuilt_with_the_ocr_text(client, session, ocr_env):
    fake, _, factory = ocr_env
    await _owner(client, session)
    body = await _upload(client, [None])
    fake.texts = {1: "kept after rebuild"}
    await runs.run(factory, _uuid(body["id"]), 1, get_settings())
    asset = await session.get(Asset, _uuid(body["id"]))
    storage = storage_from_url(get_settings().storage_url)
    base = documents.derived_prefix(asset.storage_prefix, 1)
    await storage.delete_prefix(f"{base}/pdf.md")
    await storage.delete_prefix(f"{base}/pdf.json")
    read = (await client.get(f"/api/assets/by-slug/{body['slug']}/file-mcp")).json()
    assert "kept after rebuild" in read["content"]


@pytest.mark.asyncio
async def test_each_version_has_its_own_run(client, session, ocr_env):
    _, pool, factory = ocr_env
    await _owner(client, session)
    body = await _upload(client, [None])
    await runs.run(factory, _uuid(body["id"]), 1, get_settings())
    r = await client.post(
        f"/api/assets/{body['id']}/versions",
        files=[("files", ("scan.pdf", make_pdf([None, None]), "application/pdf"))],
    )
    assert r.status_code == 201, r.text
    assert (await _ocr(client, body["slug"]))["status"] == "queued"
    old = await client.get(f"/api/assets/by-slug/{body['slug']}/ocr?version=1")
    assert old.json()["ocr"]["status"] == "done"
    assert _ocr_jobs(pool)[-1].args[1:] == (body["id"], 2)


@pytest.mark.asyncio
async def test_disabled_ocr_queues_nothing_and_refuses_requests(
    client, session, ocr_env, monkeypatch
):
    _, pool, _ = ocr_env
    monkeypatch.setattr(get_settings(), "ocr_enabled", False)
    await _owner(client, session)
    body = await _upload(client, [None])
    assert body["ocr"]["status"] == "not_requested" and body["ocr"]["available"] is False
    assert _ocr_jobs(pool) == []
    r = await client.post(f"/api/assets/{body['id']}/ocr")
    assert r.status_code == 409 and r.json()["code"] == "ocr_disabled"


@pytest.mark.asyncio
async def test_auto_ocr_off_leaves_the_scan_not_requested(client, session, ocr_env, monkeypatch):
    _, pool, _ = ocr_env
    monkeypatch.setattr(get_settings(), "ocr_auto", False)
    await _owner(client, session)
    body = await _upload(client, [None])
    assert body["ocr"]["status"] == "not_requested"
    assert _ocr_jobs(pool) == []
    r = await client.post(f"/api/assets/{body['id']}/ocr")
    assert r.status_code == 202 and r.json()["ocr"]["status"] == "queued"


@pytest.mark.asyncio
async def test_read_only_collaborator_cannot_request(client, session, ocr_env):
    owner = await _owner(client, session)
    body = await _upload(client, [None])
    viewer = await mk_user(session)
    await session.commit()
    share = await client.post(
        f"/api/assets/by-slug/{body['slug']}/shares", json={"email": viewer.email, "role": "viewer"}
    )
    assert share.status_code == 201, share.text
    await login_as(client, viewer)
    assert (await _ocr(client, body["slug"]))["status"] == "queued"
    r = await client.post(f"/api/assets/{body['id']}/ocr")
    assert r.status_code == 404
    assert owner is not None


@pytest.mark.asyncio
async def test_sweeper_requeues_a_silent_run_then_gives_up(client, session, ocr_env, monkeypatch):
    _, pool, factory = ocr_env
    await _owner(client, session)
    body = await _upload(client, [None])
    asset_id = _uuid(body["id"])
    settings = get_settings()
    monkeypatch.setattr(settings, "ocr_max_attempts", 2)

    async def make_silent(attempts: int) -> None:
        async with factory() as s:
            row = await s.get(DocumentOcr, (asset_id, 1))
            row.status, row.attempts = "running", attempts
            row.heartbeat_at = utc_now() - runs.stale_after(settings) - timedelta(seconds=5)
            await s.commit()

    await make_silent(1)
    assert await runs.sweep(factory, settings) == {"requeued": 1, "failed": 0}
    assert (await _ocr(client, body["slug"]))["status"] == "queued"
    assert _ocr_jobs(pool)[-1].kwargs["_job_id"].endswith(":1")

    await make_silent(2)
    assert await runs.sweep(factory, settings) == {"requeued": 0, "failed": 1}
    state = await _ocr(client, body["slug"])
    assert (state["status"], state["error_code"]) == ("failed", "ocr_interrupted")


@pytest.mark.asyncio
async def test_sweeper_enqueues_a_queued_run_whose_job_was_lost(client, session, ocr_env):
    _, pool, factory = ocr_env
    await _owner(client, session)
    body = await _upload(client, [None])
    async with factory() as s:
        row = await s.get(DocumentOcr, (_uuid(body["id"]), 1))
        row.requested_at = utc_now() - timedelta(minutes=10)
        await s.commit()
    before = len(_ocr_jobs(pool))
    assert await runs.sweep(factory, get_settings()) == {"requeued": 1, "failed": 0}
    assert len(_ocr_jobs(pool)) == before + 1


@pytest.mark.asyncio
async def test_saved_text_layer_is_recommended_and_replaced_only_on_request(
    client, session, ocr_env
):
    fake, pool, factory = ocr_env
    await _owner(client, session)
    data = make_pdf(["Visible cover", "notionole o déllbéré"], scanned_text=[1])
    r = await client.post("/api/assets/pdf", files=pdf_file("law.pdf", data))
    body = r.json()
    # Text the file carries is not replaced behind the reader's back.
    assert body["ocr"]["status"] == "not_requested"
    assert body["ocr"]["pages_with_hidden_text"] == 1
    assert body["ocr"]["pages_without_text"] == 0
    assert _ocr_jobs(pool) == []

    r = await client.post(f"/api/assets/{body['id']}/ocr")
    assert r.status_code == 202, r.text
    fake.texts = {2: "nationale a délibéré"}
    await runs.run(factory, _uuid(body["id"]), 1, get_settings())
    assert fake.calls == [[2]]
    read = (await client.get(f"/api/assets/by-slug/{body['slug']}/file-mcp")).json()
    assert "nationale a délibéré" in read["content"]
    assert "notionole" not in read["content"]
    assert "Visible cover" in read["content"]
    assert read["ocr"]["pages_with_hidden_text"] == 1
    assert (await _ocr(client, body["slug"]))["status"] == "done"

    # Every page has text now, yet a run on record can be repeated (a poor
    # result, a better engine) and reads the replaced layer again.
    r = await client.post(f"/api/assets/{body['id']}/ocr")
    assert r.status_code == 202, r.text
    fake.texts = {2: "nationale a délibéré et adopté"}
    await runs.run(factory, _uuid(body["id"]), 1, get_settings())
    assert fake.calls == [[2], [2]]
    read = (await client.get(f"/api/assets/by-slug/{body['slug']}/file-mcp")).json()
    assert "délibéré et adopté" in read["content"]
