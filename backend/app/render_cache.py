"""Cache of rendered Markdown, keyed by asset version and renderer fingerprint (ADR-0006).

Version bytes are immutable, and `_RENDERER_FINGERPRINT` changes with the renderer
source or its library versions, so entries never go stale. Redis is optional: any
failure falls back to rendering. Output is per document, not per user.
"""

from __future__ import annotations

import importlib.metadata
from collections.abc import Awaitable, Callable
from pathlib import Path
from uuid import UUID

import structlog

from app import markdown as markdown_module
from app import markdown_sanitize, relation_extract
from app.collections_io import read_text_at_version
from app.config import Settings
from app.markdown import render_markdown_async
from app.models import Asset
from app.redis_client import get_redis
from app.services.upload import one_chunk
from app.storage import read_all, storage_from_url
from app.util import short_sha256

log = structlog.get_logger(__name__)

# A week: long enough that a document read regularly stays warm, short
# enough that entries for versions nobody opens any more drain away.
_TTL_SECONDS = 7 * 24 * 3600

# Rendered pages above this size are served but not stored: they are rare
# and would crowd out the many small documents.
_MAX_CACHED_BYTES = 1024 * 1024

# The renderer's own source: any edit to it may change the output.
_RENDER_MODULES = (markdown_module, markdown_sanitize, relation_extract)
# Everything else the output depends on besides the source text.
_RENDER_DEPS = ("markdown-it-py", "mdit-py-plugins", "bleach", "pygments")


def _renderer_fingerprint() -> str:
    """Short hash of the renderer source and library versions; a cosmetic edit
    also invalidates, costing one re-render per document after a deploy."""
    parts: list[bytes] = []
    for module in _RENDER_MODULES:
        try:
            parts.append(Path(module.__file__ or "").read_bytes())
        except OSError:
            # Frozen or byte-compiled deployment: coarser invalidation, cache still works.
            log.warning("render_cache_source_unreadable", module=module.__name__)
    for dist in _RENDER_DEPS:
        try:
            parts.append(f"{dist}=={importlib.metadata.version(dist)}".encode())
        except importlib.metadata.PackageNotFoundError:
            parts.append(f"{dist}==?".encode())
    return short_sha256(b"\x00".join(parts), 12)


_RENDERER_FINGERPRINT = _renderer_fingerprint()


def cache_key(asset_id: UUID | str, version: int, path: str) -> str:
    """`md:{renderer}:{asset}:v{version}:{path hash}`; the path is user input, hence hashed."""
    return f"md:{_RENDERER_FINGERPRINT}:{asset_id}:v{version}:{short_sha256(path, 16)}"


async def render_asset_file(asset: Asset, version: int, rel: str, settings: Settings) -> str:
    """Rendered HTML for one file of one asset version; a missing file raises
    `FileNotFoundError`, which callers map to 404."""
    return await _render_cached(
        cache_key(asset.id, version, rel),
        lambda: read_text_at_version(asset, version, rel, settings),
    )


async def render_document(asset: Asset, version: int, settings: Settings) -> str:
    """Rendered HTML of a converted document's Markdown body (ADR-0014).

    HTML too large for Redis is stored next to the version's derived files, named by
    the renderer fingerprint so a sanitizer change still re-renders."""
    from app.services import documents  # documents imports storage helpers

    storage = storage_from_url(settings.storage_url)
    stored = f"{documents.derived_prefix(asset.storage_prefix, version)}/body.{_RENDERER_FINGERPRINT}.html"

    async def load_html() -> str | None:
        try:
            return (await read_all(storage, stored)).decode()
        except FileNotFoundError:
            return None

    async def keep_html(html: str) -> None:
        await storage.put(stored, one_chunk(html.encode()))

    return await _render_cached(
        cache_key(asset.id, version, "derived:body.md"),
        lambda: documents.body_markdown(asset, version, settings),
        load_large=load_html,
        keep_large=keep_html,
    )


async def render_derived_text(asset: Asset, version: int, text: str) -> str:
    """Rendered HTML of Markdown derived at read time (e.g. a bundle page for the agent
    view); keyed by the text hash, since its converter is not in the fingerprint."""

    async def load() -> str:
        return text

    return await _render_cached(
        cache_key(asset.id, version, f"derived:{short_sha256(text, 32)}"), load
    )


async def _render_cached(
    key: str,
    load: Callable[[], Awaitable[str]],
    *,
    load_large: Callable[[], Awaitable[str | None]] | None = None,
    keep_large: Callable[[str], Awaitable[None]] | None = None,
) -> str:
    """Redis first; HTML over `_MAX_CACHED_BYTES` goes to `keep_large` when
    the caller has a durable place for it."""
    redis = get_redis()

    try:
        hit = await redis.get(key)
    # Broad on purpose: a cache fault must never fail a document read.
    except Exception as exc:
        log.warning("render_cache_read_failed", key=key, error=str(exc))
        hit = None

    if hit is not None:
        return hit
    if load_large is not None and (large := await load_large()) is not None:
        return large

    html = await render_markdown_async(await load())

    if len(html) > _MAX_CACHED_BYTES:
        if keep_large is not None:
            await keep_large(html)
    else:
        try:
            await redis.set(key, html, ex=_TTL_SECONDS)
        except Exception as exc:
            log.warning("render_cache_write_failed", key=key, error=str(exc))

    return html
