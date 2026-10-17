"""Rescanning an asset for content links (ADR-0016, section 4): edges come back
for content stored before extraction, every linked document gets one whoever
scans, and the answer never reveals a document the caller cannot see."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models import Asset, AssetRelation, AssetShare, AuditLog, User
from app.services import relation_extraction
from app.services.relation_graph import neighbourhood
from tests.conftest import login_as, mk_asset, mk_user


async def _source(session, owner: User, text: str) -> Asset:
    """An asset whose content links somewhere but has no extracted edges,
    as content stored before extraction existed."""
    asset = await mk_asset(session, owner, title="Source")
    asset.search_content = text
    await session.commit()
    return asset


async def _targets(session, source: Asset) -> set:
    rows = await session.scalars(
        select(AssetRelation.target_asset_id)
        .where(AssetRelation.source_asset_id == source.id)
        .execution_options(populate_existing=True)
    )
    return set(rows.all())


@pytest.mark.asyncio
async def test_rescan_builds_edges_and_is_idempotent(client, session):
    owner = await mk_user(session)
    target = await mk_asset(session, owner, title="Target")
    source = await _source(session, owner, f"See [[ics:{target.slug}]].")
    await login_as(client, owner)

    r = await client.post(f"/api/assets/{source.id}/relations/rescan")
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["added"], body["removed"]) == (1, 0)
    assert body["edges"] == [[source.slug, "references", target.slug]]
    assert target.slug in body["nodes"]

    r = await client.post(f"/api/assets/{source.id}/relations/rescan")
    assert (r.json()["added"], r.json()["removed"]) == (0, 0)
    assert await _targets(session, source) == {target.id}


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["viewer", None])
async def test_rescan_needs_editor(client, session, role):
    owner = await mk_user(session)
    caller = await mk_user(session)
    target = await mk_asset(session, owner)
    source = await _source(session, owner, f"[[ics:{target.slug}]]")
    if role:
        session.add(AssetShare(asset_id=source.id, user_id=caller.id, role=role))
        await session.commit()
    await login_as(client, caller)

    r = await client.post(f"/api/assets/{source.id}/relations/rescan")
    assert r.status_code == 404
    assert r.json()["code"] == "asset_not_found"
    assert await _targets(session, source) == set()


@pytest.mark.asyncio
async def test_editor_rescan_records_every_link_but_reports_only_visible(client, session):
    """An editor who cannot see the board document rescans: the edge to it
    is recorded all the same, the answer and the audit count only what the
    editor can see, and the board member sees both edges."""
    board = await mk_user(session)
    editor = await mk_user(session)
    secret = await mk_asset(session, board, title="Board analysis")
    public = await mk_asset(session, editor, title="Public")
    session.add(AssetShare(asset_id=public.id, user_id=board.id, role="viewer"))
    source = await _source(session, board, f"[[ics:{secret.slug}]] [[ics:{public.slug}]]")
    session.add(AssetShare(asset_id=source.id, user_id=editor.id, role="editor"))
    await session.commit()

    await login_as(client, editor)
    r = await client.post(f"/api/assets/{source.id}/relations/rescan")
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["added"], body["removed"]) == (1, 0)
    assert secret.slug not in r.text
    assert body["edges"] == [[source.slug, "references", public.slug]]
    assert await _targets(session, source) == {secret.id, public.id}
    payload = await session.scalar(
        select(AuditLog.payload).where(
            AuditLog.action == "relations_rescanned", AuditLog.target == f"asset:{source.id}"
        )
    )
    assert payload == {"added": 1, "removed": 0}

    await login_as(client, board)
    r = await client.get(
        f"/api/assets/by-slug/{source.slug}/relations", params={"shape": "compact"}
    )
    assert {e[2] for e in r.json()["edges"]} == {secret.slug, public.slug}


@pytest.mark.asyncio
async def test_write_by_someone_with_less_access_keeps_the_graph(session):
    """The same text gives the same edges whoever writes it; a link that
    leaves the text takes its edge with it."""
    board = await mk_user(session)
    editor = await mk_user(session)
    secret = await mk_asset(session, board)
    source = await _source(session, board, f"[[ics:{secret.slug}]]")
    await relation_extraction.extract_for(session, source, source.search_content or "", board.id)
    await session.commit()

    kept = await relation_extraction.extract_for(
        session, source, f"[[ics:{secret.slug}]]", editor.id
    )
    assert (kept.added, kept.removed) == ([], [])
    gone = await relation_extraction.extract_for(session, source, "no links", editor.id)
    await session.commit()
    assert gone.removed == [secret.id]
    assert await _targets(session, source) == set()


@pytest.mark.asyncio
async def test_link_to_deleted_document_loses_its_edge(session):
    """A deleted target is not a hidden one: nobody can see it, so the edge
    goes and stops counting toward the asset's relation limit."""
    owner = await mk_user(session)
    target = await mk_asset(session, owner)
    source = await _source(session, owner, f"[[ics:{target.slug}]]")
    await relation_extraction.extract_for(session, source, source.search_content or "", owner.id)
    target.deleted_at = datetime.now(UTC)
    await session.commit()

    _, counts = await relation_extraction.rescan(session, source.id, owner, get_settings())
    await session.commit()
    assert counts["removed"] == 0  # the deleted target is visible to nobody
    assert await _targets(session, source) == set()


@pytest.mark.asyncio
async def test_rescan_loads_deferred_content(session):
    """A rescan reads an asset fresh from the database, where the search
    blob is a deferred column nobody has loaded yet."""
    owner = await mk_user(session)
    target = await mk_asset(session, owner)
    source = await _source(session, owner, f"[[ics:{target.slug}]]")
    session.expunge_all()
    owner = await session.get(User, owner.id)
    assert owner is not None

    _, counts = await relation_extraction.rescan(session, source.id, owner, get_settings())
    assert counts["added"] == 1


@pytest.mark.asyncio
async def test_neighbourhood_counts_skipped_visible_edges_only(session):
    owner = await mk_user(session)
    other = await mk_user(session)
    a, linked, joined = [await mk_asset(session, owner) for _ in range(3)]
    hidden = await mk_asset(session, other)

    def rel(s: Asset, t: Asset, kind: str) -> AssetRelation:
        return AssetRelation(
            source_asset_id=s.id, target_asset_id=t.id, relation_type=kind, origin="extracted"
        )

    session.add_all(
        [
            rel(a, linked, "references"),
            rel(a, joined, "references"),
            rel(a, joined, "depends_on"),
            rel(hidden, a, "references"),
        ]
    )
    await session.commit()

    full = await neighbourhood(session, owner, a)
    assert full["skipped"] == {"references": 1}
    compact = await neighbourhood(session, owner, a, shape="compact")
    assert compact["skipped"] == {"references": 1}
    assert "skipped" not in await neighbourhood(
        session, owner, a, types=["references", "depends_on"], shape="compact"
    )
    assert (await neighbourhood(session, other, hidden))["skipped"] == {}
