"""`Asset.read_tokens`: the token size of what an agent's default read returns
(the entry file, a document's Markdown, or an HTML entry page as Markdown),
stored at every content write so listings report `estimated_tokens` cheaply.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

from app.collections_io import MarkdownSources, decode_text, read_bytes_at_version
from app.config import Settings
from app.html_markdown import html_to_markdown
from app.models import Asset
from app.pdf_markdown import with_title
from app.services import documents
from app.token_estimate import tokens_for_chars, tokens_for_text

# Kinds whose stored size is roughly their text: the fallback for rows
# written before `read_tokens` existed.
_TEXT_KINDS = frozenset({"md_single", "md_collection"})


class _Sized(Protocol):
    # Read-only, so an ORM row and a Core result row both match.
    @property
    def read_tokens(self) -> int | None: ...
    @property
    def kind(self) -> str: ...
    @property
    def size_bytes(self) -> int | None: ...


def estimated_tokens(asset: _Sized) -> int | None:
    """`read_tokens`, or for an older Markdown row an estimate from its size."""
    if asset.read_tokens is not None:
        return asset.read_tokens
    if asset.kind not in _TEXT_KINDS or not asset.size_bytes:
        return None
    return tokens_for_chars(asset.size_bytes)


async def _entry_text(
    asset: Asset, settings: Settings, sources: MarkdownSources | None
) -> str | None:
    entry = asset.entry_path or ("index.md" if asset.kind == "md_single" else None)
    if entry is None:
        return None
    for rel, text in sources or ():
        if rel == entry:
            return text
    try:
        raw = await read_bytes_at_version(asset, asset.version, entry, settings)
    except FileNotFoundError:
        return None
    if asset.kind == "html_bundle":
        html = decode_text(raw)
        # BeautifulSoup is pure Python; a page can be megabytes.
        return None if html is None else await asyncio.to_thread(html_to_markdown, html)
    return raw.decode("utf-8", errors="replace")


async def refresh_read_tokens(
    asset: Asset,
    settings: Settings,
    *,
    sources: MarkdownSources | None = None,
    converted: dict[str, Any] | None = None,
) -> None:
    """Set `asset.read_tokens` for the current version. `sources` (Markdown
    files already read) and `converted` (a document's fresh conversion)
    save a storage round trip. The caller commits."""
    if documents.is_document(asset.kind):
        body = (
            bytes(converted["text_md"]).decode()
            if converted is not None
            else await documents.body_markdown(asset, asset.version, settings)
        )
        untitled = documents.document_type(asset.kind).untitled
        asset.read_tokens = tokens_for_text(with_title(asset.title, body, untitled=untitled))
        return
    text = await _entry_text(asset, settings, sources)
    asset.read_tokens = None if text is None else tokens_for_text(text)
