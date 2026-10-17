"""Upload size is enforced while streaming, not after files hit storage."""

from __future__ import annotations

import io

import pytest
from fastapi import UploadFile

from app.domain_errors import DomainError
from app.errors import domain_status
from app.services.upload import ByteBudget, chunked, put_all


def _upload(data: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename="f.bin")


@pytest.mark.asyncio
async def test_chunked_stops_once_the_budget_is_exceeded(monkeypatch):
    from app.services import upload as upload_mod

    monkeypatch.setattr(upload_mod, "_CHUNK_BYTES", 4)
    budget = ByteBudget(10)
    seen = []
    with pytest.raises(DomainError) as exc:
        async for chunk in chunked(_upload(b"x" * 40), budget):
            seen.append(chunk)
    assert domain_status(exc.value) == 413
    assert sum(len(c) for c in seen) <= 10


class _RecordingStorage:
    def __init__(self) -> None:
        self.written: dict[str, int] = {}
        self.deleted: list[str] = []

    async def put(self, key, data):
        size = 0
        async for chunk in data:
            size += len(chunk)
        self.written[key] = size
        return size

    async def delete_prefix(self, prefix):
        self.deleted.append(prefix)
        self.written = {k: v for k, v in self.written.items() if not k.startswith(prefix)}


@pytest.mark.asyncio
async def test_budget_is_shared_across_files_of_one_upload():
    storage = _RecordingStorage()
    pairs = [(_upload(b"x" * 6), "a.md"), (_upload(b"x" * 6), "b.md")]
    with pytest.raises(DomainError) as exc:
        await put_all(storage, "assets/s/v1", pairs, ByteBudget(10))
    assert domain_status(exc.value) == 413


@pytest.mark.asyncio
async def test_oversized_collection_leaves_nothing_in_storage(
    client, session, monkeypatch, fs_storage
):
    from app.config import get_settings
    from app.storage import storage_from_url
    from tests.conftest import login_as, mk_user

    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)
    settings = get_settings()
    monkeypatch.setattr(settings, "max_asset_bytes", 1000)

    files = [
        ("files", ("a.md", b"# a\\n" + b"x" * 800, "text/markdown")),
        ("files", ("b.md", b"# b\\n" + b"x" * 800, "text/markdown")),
    ]
    r = await client.post(
        "/api/assets/collection",
        files=files,
        data={"paths": ["a.md", "b.md"], "title": "big"},
    )
    assert r.status_code == 413
    assert await storage_from_url(settings.storage_url).list_prefix("assets/") == []
