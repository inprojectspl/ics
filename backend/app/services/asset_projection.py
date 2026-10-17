"""Document metadata fields shared by every asset projection (ADR-0015).
`load_metadata` fetches them for a whole page in a fixed number of queries,
so a listing costs the same for 2 or 200 rows.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Asset, User
from app.services import graph_signals
from app.services.freshness import flags, freshness
from app.services.read_size import estimated_tokens
from app.util import now as utc_now

# Lists show a preview; the full summary (max 1000 chars) is in /meta.
SUMMARY_PREVIEW_CHARS = 280


@dataclass(frozen=True)
class AssetMetadataRow:
    summary: str | None
    maintainer: dict[str, str | None] | None
    # Successor visible to the viewer (`id`, `slug`, `title`), if any.
    superseded_by: dict[str, str | None] | None = None
    # Slug of the newest visible document of the `supersedes` chain.
    latest: str | None = None
    basis_changed: bool = False


async def load_metadata(
    session: AsyncSession, assets: Sequence[Asset], viewer: User
) -> dict[UUID, AssetMetadataRow]:
    """Summary, maintainer and graph signals for `assets`, as seen by
    `viewer`. The maintainer defaults to the owner (ADR-0015) while
    `maintainer_id` is empty."""
    if not assets:
        return {}
    ids = [a.id for a in assets]
    succ = await graph_signals.latest_successors(session, viewer, ids)
    ends = await graph_signals.chain_ends(session, viewer, succ)
    changed = await graph_signals.changed_bases(session, viewer, ids)
    maintainer_id = func.coalesce(Asset.maintainer_id, Asset.owner_id)
    rows = await session.execute(
        select(Asset.id, Asset.summary, User.id, User.email, User.display_name)
        .outerjoin(User, User.id == maintainer_id)
        .where(Asset.id.in_(ids))
    )
    return {
        asset_id: AssetMetadataRow(
            summary=summary,
            maintainer=(
                {"id": str(user_id), "email": email, "display_name": display_name}
                if user_id is not None
                else None
            ),
            superseded_by=(
                {"id": str(s.id), "slug": s.slug, "title": s.title}
                if (s := succ.get(asset_id))
                else None
            ),
            latest=ends[asset_id].slug if asset_id in ends else None,
            basis_changed=asset_id in changed,
        )
        for asset_id, summary, user_id, email, display_name in rows.all()
    }


def cut_text(text: str | None, limit: int) -> str | None:
    """`text` shortened to `limit` characters, ending in an ellipsis."""
    if not text or len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def preview_summary(summary: str | None) -> str | None:
    """The summary cut to `SUMMARY_PREVIEW_CHARS` for list rows."""
    return cut_text(summary, SUMMARY_PREVIEW_CHARS)


def metadata_fields(
    asset: Asset,
    row: AssetMetadataRow | None,
    now: datetime,
    *,
    preview: bool,
) -> dict[str, Any]:
    """The metadata block of one projection. `preview` truncates the summary
    for list rows."""
    summary = row.summary if row else None
    successor = row.superseded_by if row else None
    return {
        "summary": preview_summary(summary) if preview else summary,
        "summary_source": asset.summary_source,
        "doc_type": asset.doc_type,
        "freshness": freshness(asset, now, superseded=successor is not None),
        "superseded_by": successor,
        "latest": row.latest if row else None,
        "estimated_tokens": estimated_tokens(asset),
        "flags": flags(asset, summary=summary, basis_changed=bool(row and row.basis_changed)),
        "maintainer": row.maintainer if row else None,
    }


def detail_fields(asset: Asset) -> dict[str, Any]:
    """Fields only the single-asset reads carry (`/meta` and the metadata
    writes), so the viewer and the metadata dialog see the same values after a
    reload as right after a save."""
    return {
        "summary_version": asset.summary_version,
        "maintainer_id": str(asset.maintainer_id) if asset.maintainer_id else None,
        "review_due_at": asset.review_due_at.isoformat() if asset.review_due_at else None,
        "reviewed_at": asset.reviewed_at.isoformat() if asset.reviewed_at else None,
        "reviewed_by": str(asset.reviewed_by) if asset.reviewed_by else None,
        "language": asset.language,
        "properties": dict(asset.properties or {}),
    }


async def freshness_block(session: AsyncSession, asset: Asset, viewer: User) -> dict[str, Any]:
    """Summary, doc type, size, freshness and visible successor of one asset
    for `viewer`, for the MCP reads (outline, file content): enough to pick
    between a whole read and a section read without a meta call."""
    row = (await load_metadata(session, [asset], viewer)).get(asset.id)
    fields = metadata_fields(asset, row, utc_now(), preview=False)
    return {
        key: fields[key]
        for key in (
            "summary",
            "doc_type",
            "estimated_tokens",
            "freshness",
            "superseded_by",
            "latest",
        )
    }
