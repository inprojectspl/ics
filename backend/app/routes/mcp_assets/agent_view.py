"""Agent view: `GET /by-slug/{slug}/agent-view`.

Shows the owner or an editor exactly the text an MCP agent gets from
`ics_asset_read` (the `file-mcp` endpoint) for one file, in one piece
instead of line slices, plus the same Markdown rendered by ICS.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import permissions
from app.auth import CurrentUser
from app.collections_io import count_line_reads
from app.config import get_settings
from app.db import get_session
from app.errors import ApiError
from app.html_bundle import binary_file_detail
from app.json_response import ORJSONResponse
from app.render_cache import render_asset_file, render_derived_text
from app.routes._version_param import VersionParam, resolve_version_or_404, version_echo
from app.token_estimate import tokens_for_text

from ._content import ensure_mcp_file_kind, load_agent_text, resolve_target_path
from ._router import router
from ._shared import _MAX_LINES_RANGE

# The preview returns the text whole; past this size it is cut at a line
# boundary. An agent would need hundreds of reads for such a file anyway.
AGENT_VIEW_MAX_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class _Measured:
    content: str
    total_lines: int
    shown_lines: int
    size_bytes: int
    agent_reads: int


def _measure(text: str) -> _Measured:
    """One pass over the lines for everything the response reports.

    Lines are joined with `\\n`, as `file-mcp` joins them; `content` keeps
    the lines that fit `AGENT_VIEW_MAX_BYTES`."""
    lines = text.splitlines()
    sizes = [len(line.encode("utf-8")) for line in lines]
    shown, used = 0, 0
    for size in sizes:
        used += size + (1 if shown else 0)
        if used > AGENT_VIEW_MAX_BYTES:
            break
        shown += 1
    return _Measured(
        content="\n".join(lines[:shown]),
        total_lines=len(lines),
        shown_lines=shown,
        size_bytes=sum(sizes) + max(len(lines) - 1, 0),
        agent_reads=count_line_reads(sizes),
    )


@router.get("/by-slug/{slug}/agent-view")
async def agent_view(
    slug: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    path: str | None = None,
    format: Annotated[str | None, Query(pattern=r"^(raw|markdown)$")] = None,
    version: VersionParam = None,
) -> ORJSONResponse:
    """The whole text `file-mcp` gives an agent for the same arguments, plus
    rendered `html` for Markdown (editor+). Metrics describe the full text;
    `content` is cut to `AGENT_VIEW_MAX_BYTES`."""
    asset, _ = await permissions.get_asset_with_role(
        session, user=user, min_role="editor", slug=slug
    )
    ensure_mcp_file_kind(asset, "agent-view")
    settings = get_settings()
    v = resolve_version_or_404(asset, version)
    target = await resolve_target_path(asset, path, v, settings)
    loaded = await load_agent_text(
        asset, v, target, format=format, encoding=None, settings=settings, session=session
    )
    if loaded.text is None:
        raise ApiError(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "binary_file",
            binary_file_detail(target, len(loaded.blob), "binary file; agents read it as base64"),
        )

    # A multi-megabyte page is several pure-Python passes; keep them off the loop.
    measured = await asyncio.to_thread(_measure, loaded.text)
    truncated = measured.shown_lines < measured.total_lines
    converted = loaded.extra.get("format") == "markdown"
    if not (converted or target.endswith(".md")):
        html = None
    elif converted or truncated:
        html = await render_derived_text(asset, v, measured.content)
    else:
        # The agent reads the stored file itself: same cache key as the reader.
        html = await render_asset_file(asset, v, target, settings)

    return ORJSONResponse(
        {
            "slug": asset.slug,
            "kind": asset.kind,
            "path": target,
            "content": measured.content,
            "html": html,
            "total_lines": measured.total_lines,
            "shown_lines": measured.shown_lines,
            "size_bytes": measured.size_bytes,
            "estimated_tokens": tokens_for_text(loaded.text),
            "agent_reads": measured.agent_reads,
            "lines_per_read": _MAX_LINES_RANGE,
            "truncated": truncated,
            **version_echo(asset, v),
            **loaded.extra,
        }
    )
