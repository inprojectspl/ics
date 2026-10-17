"""Relations extracted from document content (ADR-0016, section 4). Every
content write brings the source's `extracted` edges in line with the new text;
edges of other origins are never touched. An extracted edge is a fact about the
text, whoever wrote it, so access is applied only when the graph is read.
"""

from __future__ import annotations

import asyncio
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import structlog
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app import audit, permissions
from app.bundle_scan import link_hrefs
from app.collections_io import list_version_files, read_text_at_version
from app.config import Settings, get_settings
from app.models import Asset, AssetRelation, ShareLink, User
from app.relation_extract import Ref, extract_refs
from app.services import documents
from app.services.relations import MAX_EDGES_PER_ASSET, edge_count, visible_ids

log = structlog.get_logger(__name__)

# HTML bundles are read file by file; the cap bounds the work per write.
_HTML_TEXT_MAX_CHARS = 2_000_000
_HTML_EXTENSIONS = (".html", ".htm")


async def content_text(
    asset: Asset, settings: Settings, *, converted: dict[str, Any] | None = None
) -> str:
    """The text references are looked for in, for the current version:
    the Markdown of a PDF or Office document, the HTML files of a bundle,
    otherwise the search blob (every `.md` file), which a write has just
    refreshed and a rescan loads."""
    if documents.is_document(asset.kind):
        if converted is not None:
            return bytes(converted["text_md"]).decode()
        return await documents.markdown(asset, asset.version, settings)
    if asset.kind == "html_bundle":
        return await _html_text(asset, settings)
    return asset.search_content or ""


def _absolute_links(html: str, base_url: str) -> list[str]:
    """Links of a page that can point at another ICS document, made
    absolute. Relative links stay inside the bundle and are dropped;
    absolute URLs are already in the page text."""
    base = base_url.rstrip("/")
    out = []
    for href in link_hrefs(html):
        href = href.strip()
        if href.startswith("//"):
            out.append(f"https:{href}")
        elif href.startswith("/"):
            out.append(f"{base}{href}")
    return out


async def _html_text(asset: Asset, settings: Settings) -> str:
    files = await list_version_files(asset, asset.version, settings)
    pages = [rel for rel in files if rel.lower().endswith(_HTML_EXTENSIONS)]
    texts = await asyncio.gather(
        *(read_text_at_version(asset, asset.version, rel, settings) for rel in pages[:200])
    )
    html = "\n".join(texts)[:_HTML_TEXT_MAX_CHARS]
    # Root-relative links (`/v/<slug>`) carry no host for `extract_refs`.
    links = await asyncio.to_thread(_absolute_links, html, settings.base_url)
    return "\n".join([html, *links])


async def _resolve(session: AsyncSession, refs: list[Ref]) -> dict[Ref, tuple[UUID, int]]:
    """`(asset id, version)` per resolvable reference."""
    slugs = {r.value for r in refs if r.kind == "slug"}
    tokens = {r.value for r in refs if r.kind == "share_token"}
    by_slug: dict[str, tuple[UUID, int]] = {}
    by_token: dict[str, tuple[UUID, int]] = {}
    if slugs:
        # Slugs are generated lower case and refs lower-case them, so the
        # unique index on `slug` serves the lookup.
        rows = await session.execute(
            select(Asset.slug, Asset.id, Asset.version).where(
                Asset.slug.in_(slugs), Asset.deleted_at.is_(None)
            )
        )
        by_slug = {slug: (asset_id, version) for slug, asset_id, version in rows.all()}
    if tokens:
        rows_t = await session.execute(
            select(ShareLink.token, Asset.id, Asset.version)
            .join(Asset, Asset.id == ShareLink.asset_id)
            .where(ShareLink.token.in_(tokens), Asset.deleted_at.is_(None))
        )
        by_token = {token: (asset_id, version) for token, asset_id, version in rows_t.all()}
    out: dict[Ref, tuple[UUID, int]] = {}
    for ref in refs:
        target = by_slug.get(ref.value) if ref.kind == "slug" else by_token.get(ref.value)
        if target is not None:
            out[ref] = target
    return out


_EdgeKey = tuple[UUID, str | None, str | None]


@dataclass(frozen=True)
class ExtractResult:
    """Targets of the extracted edges written and removed by a run; the
    caller decides which of them it may report."""

    added: list[UUID]
    removed: list[UUID]


async def _wanted_edges(
    session: AsyncSession, asset: Asset, text: str, base_url: str
) -> dict[_EdgeKey, int]:
    """Target version per `(target, path, anchor)` referenced in `text`, in
    order of appearance."""
    if not text:
        return {}
    refs = await asyncio.to_thread(extract_refs, text, base_url)
    if not refs:
        return {}
    wanted: dict[_EdgeKey, int] = {}
    for ref, (target, version) in (await _resolve(session, refs)).items():
        if target != asset.id:
            wanted.setdefault((target, ref.path, ref.anchor), version)
    return wanted


async def extract_for(
    session: AsyncSession,
    asset: Asset,
    text: str,
    created_by: UUID | None,
    *,
    base_url: str | None = None,
) -> ExtractResult:
    """Make the `extracted` edges of `asset` match the references in `text`.
    Only the difference is written; a kept edge records the target's current
    version, as a fresh one would. Does not commit."""
    # A fresh source row must exist before its edges do.
    await session.flush()
    wanted = await _wanted_edges(session, asset, text, base_url or get_settings().base_url)
    existing = (
        await session.scalars(
            select(AssetRelation).where(
                AssetRelation.source_asset_id == asset.id, AssetRelation.origin == "extracted"
            )
        )
    ).all()
    stale: list[AssetRelation] = []
    kept: set[_EdgeKey] = set()
    for edge in existing:
        key = (edge.target_asset_id, edge.target_path, edge.target_anchor)
        version = wanted.get(key)
        if version is None or key in kept:
            stale.append(edge)
            continue
        kept.add(key)
        if edge.target_version != version:
            edge.target_version = version
    if stale:
        await session.execute(
            delete(AssetRelation).where(AssetRelation.id.in_([e.id for e in stale]))
        )
    missing = [(key, version) for key, version in wanted.items() if key not in kept]
    room = max(0, MAX_EDGES_PER_ASSET - await edge_count(session, asset.id)) if missing else 0
    rows = [
        {
            "id": uuid4(),
            "source_asset_id": asset.id,
            "target_asset_id": target,
            "relation_type": "references",
            "target_path": path,
            "target_anchor": anchor,
            "target_version": version,
            "origin": "extracted",
            "created_by": created_by,
        }
        for (target, path, anchor), version in missing[:room]
    ]
    added: list[UUID] = []
    if rows:
        added = list(
            await session.scalars(
                insert(AssetRelation)
                .values(rows)
                .on_conflict_do_nothing()
                .returning(AssetRelation.target_asset_id)
            )
        )
    return ExtractResult(added, [e.target_asset_id for e in stale])


async def extract_from_content(
    session: AsyncSession,
    asset: Asset,
    settings: Settings,
    created_by: UUID | None,
    *,
    converted: dict[str, Any] | None = None,
) -> ExtractResult:
    """`extract_for` on the current version's content (see `content_text`)."""
    # A new row gets its default version (and so its storage path) on flush.
    await session.flush()
    text = await content_text(asset, settings, converted=converted)
    return await extract_for(session, asset, text, created_by, base_url=settings.base_url)


async def _locked_for_rescan(session: AsyncSession, asset_id: UUID) -> Asset | None:
    """The asset row locked as `commit_new_version` locks it, so a version
    committed during the scan cannot get the edges of the text read before
    it, loaded fresh with the deferred search blob `content_text` reads."""
    return await session.scalar(
        select(Asset)
        .where(Asset.id == asset_id)
        .with_for_update()
        .options(undefer(Asset.search_content))
        .execution_options(populate_existing=True)
    )


async def rescan(
    session: AsyncSession,
    asset_id: UUID,
    actor: User,
    settings: Settings,
    *,
    transport: str | None = None,
    client_id_external: str | None = None,
) -> tuple[Asset, dict[str, int]]:
    """Extract relations from the current version again without a new one,
    for content stored before extraction existed. Needs editor. The counts
    returned and audited cover only targets `actor` can see, so a rescan
    never tells whether a linked document it cannot open exists. Does not
    commit."""
    await permissions.get_asset_with_role(session, user=actor, min_role="editor", asset_id=asset_id)
    asset = await _locked_for_rescan(session, asset_id)
    assert asset is not None  # the role check above found it
    result = await extract_from_content(session, asset, settings, actor.id)
    visible = await visible_ids(session, actor, {*result.added, *result.removed})
    counts = {
        "added": sum(t in visible for t in result.added),
        "removed": sum(t in visible for t in result.removed),
    }
    await audit.record(
        session,
        actor=actor,
        action="relations_rescanned",
        target=f"asset:{asset.id}",
        payload=counts,
        transport=transport,
        client_id_external=client_id_external,
    )
    return asset, counts


@dataclass
class RescanTotals:
    assets: int = 0
    added: int = 0
    removed: int = 0
    failed: int = 0


async def rescan_all(
    session: AsyncSession, settings: Settings, *, kinds: Collection[str] | None = None
) -> RescanTotals:
    """`rescan` of every live asset for the operator backfill, committing
    per asset; an asset whose content cannot be read is logged and skipped."""
    stmt = select(Asset.id).where(Asset.deleted_at.is_(None)).order_by(Asset.created_at)
    if kinds:
        stmt = stmt.where(Asset.kind.in_(kinds))
    totals = RescanTotals()
    for asset_id in (await session.scalars(stmt)).all():
        try:
            asset = await _locked_for_rescan(session, asset_id)
            if asset is None:
                continue
            result = await extract_from_content(session, asset, settings, None)
            await session.commit()
        except Exception:
            await session.rollback()
            log.exception("relations_rescan_failed", asset_id=str(asset_id))
            totals.failed += 1
            continue
        totals.assets += 1
        totals.added += len(result.added)
        totals.removed += len(result.removed)
    return totals
