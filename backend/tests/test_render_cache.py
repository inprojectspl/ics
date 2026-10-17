"""Cache of rendered Markdown, keyed by asset version.

What these tests pin down is the correctness story, not the speed: a
reader must never see the HTML of a version other than the one asked
for, and a cache fault must never turn into a failed read.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app import render_cache
from app.models import Asset
from app.redis_client import get_redis
from tests.conftest import login_as as _login
from tests.conftest import mk_asset, mk_user, put_blob


async def _doc_html(client, asset: Asset, version: int | None = None) -> str:
    url = f"/api/assets/by-slug/{asset.slug}/doc"
    if version is not None:
        url += f"?version={version}"
    r = await client.get(url)
    assert r.status_code == 200, r.text
    return r.json()["html"]


@pytest.mark.asyncio
async def test_second_read_is_served_from_cache(client, session, fs_storage):
    """A second read of the same document does not render it again."""
    user = await mk_user(session)
    asset = await mk_asset(session, user, title="Cached")
    await put_blob(asset, "doc.md", b"# Title\n\nbody")
    await session.commit()
    await _login(client, user)

    first = await _doc_html(client, asset)
    assert "Title" in first

    with patch.object(
        render_cache, "render_markdown_async", side_effect=AssertionError("rendered again")
    ):
        second = await _doc_html(client, asset)

    assert second == first


@pytest.mark.asyncio
async def test_new_version_is_rendered_fresh(client, session, fs_storage):
    """A new version is a new key, so a content change is visible immediately."""
    user = await mk_user(session)
    asset = await mk_asset(session, user, title="Edited")
    await put_blob(asset, "doc.md", b"# First version")
    await session.commit()
    await _login(client, user)

    assert "First version" in await _doc_html(client, asset)

    r = await client.put(
        f"/api/assets/{asset.id}/content",
        json={"content": "# Second version"},
    )
    assert r.status_code == 201, r.text

    await session.refresh(asset)
    assert asset.version == 2
    html = await _doc_html(client, asset)
    assert "Second version" in html
    assert "First version" not in html


@pytest.mark.asyncio
async def test_previous_version_keeps_its_own_html(client, session, fs_storage):
    """A preview of an older version does not get the current content, and vice versa."""
    user = await mk_user(session)
    asset = await mk_asset(session, user, title="Two versions")
    await put_blob(asset, "doc.md", b"# Old content")
    await session.commit()
    await _login(client, user)

    await _doc_html(client, asset)  # warm v1
    r = await client.put(
        f"/api/assets/{asset.id}/content",
        json={"content": "# New content"},
    )
    assert r.status_code == 201, r.text
    await session.refresh(asset)

    assert "New content" in await _doc_html(client, asset)
    assert "Old content" in await _doc_html(client, asset, version=1)


@pytest.mark.asyncio
async def test_read_survives_a_broken_cache(client, session, fs_storage):
    """A dead Redis degrades to rendering, not to an error."""
    user = await mk_user(session)
    asset = await mk_asset(session, user, title="No redis")
    await put_blob(asset, "doc.md", b"# Works regardless")
    await session.commit()
    await _login(client, user)

    class _Broken:
        async def get(self, *_a, **_kw):
            raise ConnectionError("redis down")

        async def set(self, *_a, **_kw):
            raise ConnectionError("redis down")

    with patch.object(render_cache, "get_redis", return_value=_Broken()):
        html = await _doc_html(client, asset)

    assert "Works regardless" in html


def test_key_changes_with_version_and_path():
    a = "11111111-1111-1111-1111-111111111111"
    assert render_cache.cache_key(a, 1, "doc.md") != render_cache.cache_key(a, 2, "doc.md")
    assert render_cache.cache_key(a, 1, "doc.md") != render_cache.cache_key(a, 1, "other.md")
    assert render_cache.cache_key(a, 1, "doc.md") == render_cache.cache_key(a, 1, "doc.md")


@pytest.mark.parametrize("source", ["markdown.py", "markdown_sanitize.py", "relation_extract.py"])
def test_fingerprint_follows_the_renderer_source(source):
    """Any change in the renderer or sanitizer source (allowlist, plugin,
    highlighter) must invalidate entries on its own, without remembering a
    manual schema number."""
    before = render_cache._renderer_fingerprint()
    assert before == render_cache._renderer_fingerprint()

    real_read = Path.read_bytes

    def _changed_source(self, *a, **kw):
        if self.name == source:
            return real_read(self, *a, **kw) + b"\n# renderer change\n"
        return real_read(self, *a, **kw)

    with patch.object(Path, "read_bytes", _changed_source):
        assert render_cache._renderer_fingerprint() != before


def test_fingerprint_follows_renderer_dependencies():
    """A renderer library bump changes the HTML without touching our code,
    so it must be part of the key too."""
    before = render_cache._renderer_fingerprint()
    real_version = render_cache.importlib.metadata.version

    def _bumped(dist: str) -> str:
        return "99.0.0" if dist == "bleach" else real_version(dist)

    with patch.object(render_cache.importlib.metadata, "version", _bumped):
        assert render_cache._renderer_fingerprint() != before


def test_no_route_renders_markdown_outside_the_cache():
    """The cache is the only path to rendering. A direct call to
    `render_markdown_async` in a handler would silently bypass it."""
    app_dir = Path(render_cache.__file__).parent
    allowed = {"markdown.py", "render_cache.py"}
    offenders = [
        path.relative_to(app_dir).as_posix()
        for path in app_dir.rglob("*.py")
        if path.name not in allowed and "render_markdown" in path.read_text()
    ]
    assert offenders == []


@pytest.mark.asyncio
async def test_oversized_html_is_served_but_not_stored(session, fs_storage):
    """Huge documents do not take up Redis space; they still render."""
    from app.config import get_settings

    user = await mk_user(session)
    asset = await mk_asset(session, user, title="Big")
    big = "x" * (render_cache._MAX_CACHED_BYTES + 1)
    await put_blob(asset, "doc.md", big.encode())
    await session.commit()

    html = await render_cache.render_asset_file(asset, 1, "doc.md", get_settings())
    assert big[:50] in html
    stored = await get_redis().get(render_cache.cache_key(asset.id, 1, "doc.md"))
    assert stored is None
