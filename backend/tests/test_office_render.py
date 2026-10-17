"""Rendering of converted documents: HTML too big for Redis is kept next
to the version, so a long document is not re-rendered on every view."""

from __future__ import annotations

import pytest

from app import render_cache
from app.config import get_settings
from app.storage import storage_from_url
from tests.conftest import login_as, mk_user
from tests.office_factory import make_docx, office_file


@pytest.mark.asyncio
async def test_large_rendered_document_is_kept_in_storage(client, session, fs_storage, monkeypatch):
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)
    r = await client.post(
        "/api/assets/document",
        files=office_file("long.docx", make_docx([("p", f"paragraph {n}") for n in range(200)])),
    )
    assert r.status_code == 201, r.text
    slug = r.json()["slug"]

    monkeypatch.setattr(render_cache, "_MAX_CACHED_BYTES", 100)
    renders = 0
    real_render = render_cache.render_markdown_async

    async def counting_render(text: str) -> str:
        nonlocal renders
        renders += 1
        return await real_render(text)

    monkeypatch.setattr(render_cache, "render_markdown_async", counting_render)

    first = (await client.get(f"/api/assets/by-slug/{slug}/doc")).json()["html"]
    second = (await client.get(f"/api/assets/by-slug/{slug}/doc")).json()["html"]
    assert "paragraph 199" in first
    assert second == first
    assert renders == 1
    storage = storage_from_url(get_settings().storage_url)
    kept = [k for k in await storage.list_prefix("assets/") if k.endswith(".html")]
    assert len(kept) == 1
    assert "/derived/v1/body." in kept[0]
