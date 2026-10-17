"""Building the outline of assets (Markdown, HTML, PDF and Office documents).
The worker (`jobs/tasks/outline.py`) owns the status flow, persistence and the
audit log; this module only reads storage and builds the payload.
"""

from __future__ import annotations

import asyncio

from app.config import Settings
from app.models import Asset
from app.outline_parser import (
    build_document,
    build_html_bundle,
    build_md_collection,
    build_md_single,
    cap_outline,
)
from app.services import documents
from app.storage import read_all, storage_from_url

_READ_CONCURRENCY = 16


async def _read_collection(storage, prefix: str) -> list[tuple[str, str]]:
    """Returns (relative_path, content_text) for every .md under prefix."""
    keys = [k for k in await storage.list_prefix(prefix) if k.endswith(".md")]
    sem = asyncio.Semaphore(_READ_CONCURRENCY)

    async def _one(key: str) -> tuple[str, str]:
        async with sem:
            data = await read_all(storage, key)
        rel = key[len(prefix) :].lstrip("/")
        try:
            return rel, data.decode("utf-8")
        except UnicodeDecodeError:
            return rel, ""

    return list(await asyncio.gather(*(_one(k) for k in keys)))


async def _read_bundle_files(storage, prefix: str) -> list[tuple[str, int]]:
    """(relative_path, size_bytes) for every file under prefix, from the
    listing alone: the bundle outline needs no file content."""
    return [
        (key[len(prefix) :].lstrip("/"), size)
        for key, size in await storage.list_prefix_stats(prefix)
    ]


async def build_outline_payload(asset: Asset, settings: Settings) -> dict:
    """Capped outline of the asset's current version, for `Asset.outline_json`.
    I/O errors propagate; the worker turns them into the `failed` status."""
    storage = storage_from_url(settings.storage_url, settings)
    prefix = f"{asset.storage_prefix.rstrip('/')}/v{asset.version}/"
    if asset.kind == "md_single":
        md_key = f"{prefix}{asset.entry_path or 'index.md'}"
        content = (await read_all(storage, md_key)).decode("utf-8", errors="replace")
        outline = build_md_single(content, asset.title)
    elif asset.kind == "md_collection":
        files = await _read_collection(storage, prefix)
        outline = build_md_collection(asset.entry_path, files, asset.title)
    elif asset.kind == "html_bundle":
        bundle_files = await _read_bundle_files(storage, prefix)
        outline = build_html_bundle(asset.entry_path, bundle_files, asset.title)
    elif documents.is_document(asset.kind):
        meta = await documents.load_meta(asset, asset.version, settings)
        md = await documents.markdown(asset, asset.version, settings)
        extra = documents.summary_of(asset.kind, meta)
        if "bookmarks" in meta:
            extra["bookmarks"] = meta["bookmarks"]
        outline = build_document(
            asset.kind, md, asset.title, extra=extra, truncated=meta["truncated"]
        )
    else:
        outline = {"kind": asset.kind, "truncated": False}
    return cap_outline(outline)
