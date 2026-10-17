"""Markdown text for `Asset.search_content`, recomputed on every content write.

Document conversion and OCR fill the field themselves; ranking is in
`services.document_search`. No incremental index: rereading on write is cheap
next to the upload.
"""

from __future__ import annotations

from app.collections_io import MarkdownSources, read_markdown_files
from app.config import Settings
from app.models import Asset


async def compute_search_content(
    asset: Asset, settings: Settings, *, sources: MarkdownSources | None = None
) -> str | None:
    """Every .md file of the current version concatenated; None for html_bundle or
    no .md content. `sources` saves a reread when the caller has the files."""
    if asset.kind == "html_bundle":
        return None
    if sources is None:
        sources = await read_markdown_files(asset, settings)
    # Listing order keeps the blob deterministic.
    parts = [text for rel, text in sources if rel.lower().endswith(".md")]
    if not parts:
        return None
    return "\n\n".join(parts)


async def refresh_search_content(
    asset: Asset, settings: Settings, *, sources: MarkdownSources | None = None
) -> None:
    """Compute and write back the search blob. Caller still drives the
    commit; this just mutates the asset row."""
    asset.search_content = await compute_search_content(asset, settings, sources=sources)
