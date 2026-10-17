"""Recovery of a PDF's derived files (`pdf.json`, `pdf.md`).

Two readers rebuilding the same version at once must not read a derived file
the other one has just truncated and return a document without its text.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models import Asset
from app.services import documents
from app.services.upload import one_chunk
from app.storage import storage_from_url
from tests.conftest import login_as, mk_user
from tests.pdf_factory import make_pdf, pdf_file


async def _pdf_asset(client, session, text: str) -> Asset:
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)
    r = await client.post("/api/assets/pdf", files=pdf_file("notes.pdf", make_pdf([text])))
    assert r.status_code == 201, r.text
    asset = await session.scalar(select(Asset).where(Asset.slug == r.json()["slug"]))
    assert asset is not None
    return asset


@pytest.mark.asyncio
async def test_concurrent_rebuilds_return_the_full_text(client, session, fs_storage):
    asset = await _pdf_asset(client, session, "text that must survive a race")
    settings = get_settings()
    storage = storage_from_url(settings.storage_url)
    await storage.delete_prefix(documents.derived_prefix(asset.storage_prefix, 1))

    results = await asyncio.gather(
        *(documents.markdown(asset, 1, settings) for _ in range(3)),
        *(documents.load_meta(asset, 1, settings) for _ in range(3)),
    )
    for md in results[:3]:
        assert "text that must survive a race" in md
    for meta in results[3:]:
        assert meta["page_count"] == 1


@pytest.mark.asyncio
async def test_empty_or_broken_derived_files_are_rebuilt(client, session, fs_storage):
    asset = await _pdf_asset(client, session, "rebuilt after damage")
    settings = get_settings()
    storage = storage_from_url(settings.storage_url)
    derived = documents.derived_prefix(asset.storage_prefix, 1)
    await storage.put(f"{derived}/pdf.json", one_chunk(b'{"page_co'))
    await storage.put(f"{derived}/pdf.md", one_chunk(b""))

    assert (await documents.load_meta(asset, 1, settings))["page_count"] == 1
    assert "rebuilt after damage" in await documents.markdown(asset, 1, settings)
