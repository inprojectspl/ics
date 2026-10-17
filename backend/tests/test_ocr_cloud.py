"""Cloud OCR (ADR-0021): the Mistral provider against a mocked API, the PDF
chunking child, the reader's API key (encrypted in Redis for one run, never
kept after it) and Markdown output kept with its tables."""

from __future__ import annotations

import base64
import io
import json
from collections.abc import Sequence
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import httpx
import pytest
from pypdf import PdfReader
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings, get_settings
from app.jobs import queue as queue_mod
from app.pdf_markdown import pages_markdown
from app.redis_client import get_redis
from app.services.ocr import mistral, providers, runs, secrets
from app.services.ocr.mistral import MistralProvider
from app.services.ocr.providers import OcrFailure, PageCallback
from tests.conftest import login_as, mk_user
from tests.pdf_factory import make_pdf, pdf_file


def _pages_in(request: httpx.Request) -> int:
    body = json.loads(request.content)
    data = body["document"]["document_url"].split(",", 1)[1]
    return len(PdfReader(io.BytesIO(base64.b64decode(data))).pages)


class _Mock(MistralProvider):
    def __init__(self, handler) -> None:
        self.transport = httpx.MockTransport(handler)


async def _read(provider, pages, monkeypatch, key="sk-test"):
    monkeypatch.setattr(get_settings(), "ocr_mistral_chunk_pages", 2)
    got: dict[int, str] = {}

    async def on_page(number: int, text: str) -> None:
        got[number] = text

    engine = await provider.recognize(
        make_pdf(["a", None, "c", None]), pages, get_settings(), on_page, api_key=key
    )
    return engine, got


@pytest.mark.asyncio
async def test_mistral_sends_chunks_and_maps_pages_back(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.headers["authorization"], _pages_in(request)))
        count = len(json.loads(request.content)["pages"])
        return httpx.Response(
            200,
            json={
                "model": "mistral-ocr-4-0",
                "pages": [{"index": i, "markdown": f"md {len(seen)}.{i}"} for i in range(count)],
            },
        )

    engine, got = await _read(_Mock(handler), [2, 3, 4], monkeypatch)
    assert engine == "mistral mistral-ocr-4-0"
    assert got == {2: "md 1.0", 3: "md 1.1", 4: "md 2.0"}
    assert seen == [("Bearer sk-test", 2), ("Bearer sk-test", 1)]


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "ocr_api_key_invalid"),
        (402, "ocr_provider_quota"),
        (413, "ocr_provider_too_large"),
        (422, "ocr_provider_rejected"),
        (429, "ocr_provider_rate_limited"),
        (503, "ocr_provider_error"),
    ],
)
@pytest.mark.asyncio
async def test_mistral_refusals_become_codes(monkeypatch, status, code):
    monkeypatch.setattr(mistral.asyncio, "sleep", AsyncMock())
    provider = _Mock(lambda request: httpx.Response(status, json={"message": "no"}))
    with pytest.raises(OcrFailure) as exc:
        await _read(provider, [1], monkeypatch)
    assert exc.value.code == code


@pytest.mark.asyncio
async def test_mistral_retries_a_rate_limit(monkeypatch):
    monkeypatch.setattr(mistral.asyncio, "sleep", AsyncMock())
    answers = iter(
        [
            httpx.Response(429, headers={"retry-after": "1"}),
            httpx.Response(200, json={"pages": [{"index": 0, "markdown": "ok"}]}),
        ]
    )
    _, got = await _read(_Mock(lambda request: next(answers)), [1], monkeypatch)
    assert got == {1: "ok"}


@pytest.mark.asyncio
async def test_mistral_without_a_key_fails_before_any_request(monkeypatch):
    with pytest.raises(OcrFailure) as exc:
        await _read(_Mock(lambda r: httpx.Response(500)), [1], monkeypatch, key=None)
    assert exc.value.code == "ocr_api_key_missing"


def test_markdown_ocr_keeps_tables_but_not_headings_or_images():
    md = pages_markdown(
        ["# Title\n![img-0.jpeg](img-0.jpeg)\n| a | b |\n|---|---|\n| 1 | 2 |\n---"],
        {1},
        ocr_markdown=True,
    )
    assert "**Title**" in md and "| a | b |\n|---|---|\n| 1 | 2 |" in md
    assert "![" not in md and "\n---" not in md.split("| 1 | 2 |")[1]
    assert md.count("## ") == 1


class FakeCloud:
    name = "cloud"
    needs_api_key = True
    markdown = True

    def __init__(self) -> None:
        self.keys: list[str | None] = []

    async def recognize(
        self,
        pdf: bytes,
        pages: Sequence[int],
        settings: Settings,
        on_page: PageCallback,
        *,
        api_key: str | None = None,
    ) -> str:
        self.keys.append(api_key)
        for number in pages:
            await on_page(number, "| col | val |\n|---|---|\n| x | 1 |")
        return "cloud 1"


@pytest.fixture
def cloud(monkeypatch, fs_storage):
    fake = FakeCloud()
    monkeypatch.setitem(providers.PROVIDERS, "cloud", fake)
    monkeypatch.setattr(get_settings(), "ocr_providers", ["local", "cloud"])
    pool = MagicMock()
    pool.enqueue_job = AsyncMock()
    monkeypatch.setattr(queue_mod, "get_pool", AsyncMock(return_value=pool))
    return fake


@pytest.mark.asyncio
async def test_cloud_run_uses_the_pasted_key_once(client, session, cloud):
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)
    body = (await client.post("/api/assets/pdf", files=pdf_file("s.pdf", make_pdf([None])))).json()
    assert [p["name"] for p in body["ocr"]["providers"]] == ["local", "cloud"]
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    await runs.run(factory, UUID(body["id"]), 1, get_settings())  # the automatic local run

    r = await client.post(f"/api/assets/{body['id']}/ocr", json={"provider": "cloud"})
    assert r.status_code == 400 and r.json()["code"] == "ocr_api_key_required"
    r = await client.post(f"/api/assets/{body['id']}/ocr", json={"provider": "nope"})
    assert r.status_code == 400 and r.json()["code"] == "ocr_provider_unknown"

    r = await client.post(
        f"/api/assets/{body['id']}/ocr", json={"provider": "cloud", "api_key": " sk-secret "}
    )
    assert r.status_code == 202, r.text
    assert r.json()["ocr"]["provider"] == "cloud"
    stored = await get_redis().get(f"ocr:api-key:{body['id']}:1")
    assert stored and "sk-secret" not in stored

    await runs.run(factory, UUID(body["id"]), 1, get_settings())
    assert cloud.keys == ["sk-secret"]
    assert await secrets.load(body["id"], 1, get_settings()) is None
    read = (await client.get(f"/api/assets/by-slug/{body['slug']}/file-mcp")).json()
    assert "| col | val |\n|---|---|\n| x | 1 |" in read["content"]
    assert read["ocr"]["status"] == "done"


@pytest.mark.asyncio
async def test_cloud_run_without_its_key_fails_with_a_code(client, session, cloud, monkeypatch):
    monkeypatch.setattr(get_settings(), "ocr_auto", False)
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)
    body = (await client.post("/api/assets/pdf", files=pdf_file("s.pdf", make_pdf([None])))).json()
    r = await client.post(
        f"/api/assets/{body['id']}/ocr", json={"provider": "cloud", "api_key": "sk"}
    )
    assert r.status_code == 202
    await secrets.delete(body["id"], 1)  # expired while queued
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    await runs.run(factory, UUID(body["id"]), 1, get_settings())
    state = (await client.get(f"/api/assets/by-slug/{body['slug']}/ocr")).json()["ocr"]
    assert (state["status"], state["error_code"]) == ("failed", "ocr_api_key_missing")
    assert cloud.keys == []
