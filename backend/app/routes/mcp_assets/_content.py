"""What an agent reads from a file of an asset, before line slicing.

Shared by `file-mcp` (the MCP read) and `agent-view` (the owner's preview of
that read), so the preview cannot drift from what the agent actually gets.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.collections_io import decode_text, normalize_collection_path, read_bytes_at_version
from app.config import Settings
from app.errors import ApiError
from app.html_bundle import is_allowed_path
from app.html_markdown import html_to_markdown
from app.models import Asset
from app.services import documents, ocr
from app.services.versions import entry_path_at_version

from ._shared import _MCP_FILE_KINDS


def ensure_mcp_file_kind(asset: Asset, endpoint: str) -> None:
    """400 for a kind the per-file MCP reads do not cover."""
    if asset.kind not in _MCP_FILE_KINDS:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "unsupported_kind",
            f"{endpoint} supports {'/'.join(sorted(_MCP_FILE_KINDS))} only",
        )


async def resolve_target_path(
    asset: Asset, path: str | None, version: int, settings: Settings
) -> str:
    """Resolve and validate the file to read within the asset.

    Single-file kinds ignore `path`; without one the version's own entry is
    used. Bundle paths pass the same allowlist as `serve_bundle_file`, so
    file-mcp cannot reach anything the static route wouldn't serve.
    """
    target = None if asset.kind == "md_single" or documents.is_document(asset.kind) else path
    if target is None:
        target = await entry_path_at_version(asset, version, settings)
    if target is None and asset.kind == "md_single":
        target = "index.md"
    if target is None:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "path_required", "path required for collection")
    target = normalize_collection_path(target)  # 400 on traversal/absolute/empty
    if asset.kind == "html_bundle" and not is_allowed_path(target):
        # Mirror serve_bundle_file: disallowed extensions read as absent.
        raise ApiError(status.HTTP_404_NOT_FOUND, "file_not_found", "file not found")
    return target


@dataclass(frozen=True)
class AgentText:
    """The whole text `file-mcp` slices into `content`.

    `text` is None for a binary file; `blob` then holds its bytes. `extra`
    carries the response fields that depend on the content (`format`, and
    for a document its summary such as `page_count`)."""

    text: str | None
    blob: bytes = b""
    extra: dict[str, Any] = field(default_factory=dict)


async def load_agent_text(
    asset: Asset,
    version: int,
    target: str,
    *,
    format: str | None,
    encoding: str | None,
    settings: Settings,
    session: AsyncSession,
) -> AgentText:
    """Read `target` the way `file-mcp` does for the given `format`/`encoding`.
    A document reads as converted Markdown, with its OCR state in `extra`."""
    if documents.is_document(asset.kind) and format != "raw" and encoding != "base64":
        # Sequential: after a lost derived file the first call rebuilds both.
        meta = await documents.load_meta(asset, version, settings)
        text = await documents.markdown(asset, version, settings)
        extra = {"format": "markdown", **documents.summary_of(asset.kind, meta)}
        block = await ocr.ocr_block(session, asset, version, settings, meta=meta)
        if block is not None:
            extra["ocr"] = block
        return AgentText(text, extra=extra)

    to_markdown = format == "markdown"
    if to_markdown and not target.lower().endswith((".html", ".htm")):
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, "html_only", "format=markdown works on .html files only"
        )
    try:
        blob = await read_bytes_at_version(asset, version, target, settings)
    except FileNotFoundError as e:
        raise ApiError(status.HTTP_404_NOT_FOUND, "file_not_found", "file not found") from e

    if asset.kind == "html_bundle" or documents.is_document(asset.kind):
        # Strict decode tells text from binary; a document is always binary.
        decoded = None if documents.is_document(asset.kind) else decode_text(blob)
        if decoded is None:
            return AgentText(None, blob)
        text = decoded
    else:
        text = blob.decode("utf-8", errors="replace")

    if not to_markdown:
        return AgentText(text)
    # BeautifulSoup is pure Python and a bundle page can be megabytes,
    # so the conversion runs off the event loop.
    return AgentText(await asyncio.to_thread(html_to_markdown, text), extra={"format": "markdown"})
