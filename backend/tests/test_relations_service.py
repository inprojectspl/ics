"""Relation service (ADR-0016): canonical storage, origin, limits, cycles
checked only among visible documents, and hidden ends reported as missing."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.domain_errors import (
    ConflictError,
    DomainError,
    InvalidInputError,
    LimitExceededError,
    NotFoundError,
)
from app.errors import domain_status
from app.models import AssetRelation, AssetShare, AuditLog
from app.services import graph_signals, relations
from app.services.freshness import freshness
from tests.conftest import mk_asset, mk_user


async def _edge(session, user, source, target, relation_type="depends_on", **kw):
    return await relations.add_relation(
        session,
        actor=user,
        source_id=source.id,
        target_id=target.id,
        relation_type=relation_type,
        **kw,
    )


async def _owner_with(session, n):
    owner = await mk_user(session)
    assets = [await mk_asset(session, owner) for _ in range(n)]
    await session.commit()
    return owner, assets


@pytest.mark.asyncio
async def test_symmetric_relation_is_one_row_in_canonical_order(session):
    owner, (a, b) = await _owner_with(session, 2)
    edge = await _edge(session, owner, a, b, "relates_to")
    assert (edge.source_asset_id, edge.target_asset_id) == tuple(sorted((a.id, b.id)))

    with pytest.raises(ConflictError) as exc:
        await _edge(session, owner, b, a, "relates_to")
    assert exc.value.code == "relation_exists"
    count = await session.scalar(
        select(func.count()).where(
            AssetRelation.source_asset_id.in_([a.id, b.id]),
            AssetRelation.target_asset_id.in_([a.id, b.id]),
        )
    )
    assert count == 1


@pytest.mark.asyncio
async def test_agent_supersedes_is_effective_immediately(session):
    owner, (new, old) = await _owner_with(session, 2)
    edge = await _edge(session, owner, new, old, "supersedes", transport="bearer")
    await session.commit()

    row = await session.get(AssetRelation, edge.id)
    assert row is not None
    assert row.origin == "agent"
    assert row.target_version == old.version
    successors = await graph_signals.latest_successors(session, owner, [old.id])
    assert successors[old.id].id == new.id
    assert freshness(old, datetime.now(UTC), superseded=old.id in successors) == "superseded"

    actions = (
        await session.scalars(
            select(AuditLog.action).where(AuditLog.target == f"relation:{edge.id}")
        )
    ).all()
    assert actions == ["relation_added"]


@pytest.mark.asyncio
async def test_cookie_origin_is_manual_and_takes_over_extracted_edge(session):
    owner, (a, b) = await _owner_with(session, 2)
    edge = await _edge(session, owner, a, b, "references", origin="extracted")
    assert edge.origin == "extracted"
    again = await _edge(session, owner, a, b, "references", transport="cookie")
    assert again.id == edge.id
    assert again.origin == "manual"
    with pytest.raises(ConflictError):
        await _edge(session, owner, a, b, "references")


@pytest.mark.asyncio
async def test_cycle_through_invisible_document_is_not_refused(session):
    """B -> C -> A exist, C is hidden from the actor: adding A -> B closes a
    real cycle, but refusing it would reveal the hidden path."""
    owner, (a, b, c) = await _owner_with(session, 3)
    actor = await mk_user(session)
    session.add_all(
        [
            AssetShare(asset_id=a.id, user_id=actor.id, role="editor"),
            AssetShare(asset_id=b.id, user_id=actor.id, role="viewer"),
        ]
    )
    await session.commit()
    await _edge(session, owner, b, c, "supersedes")
    await _edge(session, owner, c, a, "supersedes")

    edge = await _edge(session, actor, a, b, "supersedes")
    assert edge.origin == "manual"


@pytest.mark.asyncio
async def test_visible_cycle_is_refused(session):
    owner, (a, b, c) = await _owner_with(session, 3)
    await _edge(session, owner, b, c, "part_of")
    await _edge(session, owner, c, a, "part_of")
    with pytest.raises(ConflictError) as exc:
        await _edge(session, owner, a, b, "part_of")
    assert exc.value.code == "relation_cycle"
    # Other types may form cycles freely.
    await _edge(session, owner, a, b, "depends_on")
    await _edge(session, owner, b, a, "depends_on")


@pytest.mark.asyncio
async def test_limit_and_self_edge_and_unknown_type(session, monkeypatch):
    owner, (a, b, c, d) = await _owner_with(session, 4)
    monkeypatch.setattr(relations, "MAX_EDGES_PER_ASSET", 2)
    await _edge(session, owner, a, b)
    await _edge(session, owner, a, c)
    with pytest.raises(LimitExceededError) as exc:
        await _edge(session, owner, a, d)
    assert exc.value.code == "relation_limit"
    # The target side counts too.
    with pytest.raises(LimitExceededError):
        await _edge(session, owner, d, a)

    with pytest.raises(InvalidInputError) as exc_self:
        await _edge(session, owner, b, b)
    assert exc_self.value.code == "relation_self"
    with pytest.raises(InvalidInputError) as exc_type:
        await _edge(session, owner, b, c, "blocks")
    assert exc_type.value.code == "relation_type_invalid"


@pytest.mark.asyncio
async def test_invisible_target_looks_exactly_like_a_missing_one(session):
    owner, (a,) = await _owner_with(session, 1)
    _other, (hidden,) = await _owner_with(session, 1)

    errors = []
    for target_id in (hidden.id, uuid4()):
        with pytest.raises(DomainError) as exc:
            await relations.add_relation(
                session,
                actor=owner,
                source_id=a.id,
                target_id=target_id,
                relation_type="depends_on",
            )
        errors.append((type(exc.value), exc.value.code, exc.value.detail))
    assert errors[0] == errors[1] == (NotFoundError, "asset_not_found", "asset not found")


@pytest.mark.asyncio
async def test_viewer_of_source_cannot_add(session):
    _owner, (a, b) = await _owner_with(session, 2)
    viewer = await mk_user(session)
    session.add_all(AssetShare(asset_id=x.id, user_id=viewer.id, role="viewer") for x in (a, b))
    await session.commit()
    with pytest.raises(NotFoundError) as exc:
        await _edge(session, viewer, a, b)
    assert domain_status(exc.value) == 404


@pytest.mark.asyncio
async def test_remove_needs_editor_on_one_end_and_both_visible(session):
    owner, (a, b, c) = await _owner_with(session, 3)
    user = await mk_user(session)
    session.add_all(
        [
            AssetShare(asset_id=a.id, user_id=user.id, role="viewer"),
            AssetShare(asset_id=b.id, user_id=user.id, role="editor"),
        ]
    )
    await session.commit()
    ab = await _edge(session, owner, a, b)
    ac = await _edge(session, owner, a, c)
    await session.commit()

    # c is invisible: the edge does not exist for this user.
    with pytest.raises(NotFoundError) as exc:
        await relations.remove_relation(session, actor=user, relation_id=ac.id)
    assert exc.value.code == "relation_not_found"
    with pytest.raises(NotFoundError):
        await relations.remove_relation(session, actor=user, relation_id=uuid4())

    # Editor on the target only is enough.
    await relations.remove_relation(session, actor=user, relation_id=ab.id)
    assert await session.get(AssetRelation, ab.id) is None


@pytest.mark.asyncio
async def test_update_note_and_refresh_target_version(session):
    owner, (a, b) = await _owner_with(session, 2)
    edge = await _edge(session, owner, a, b, "derived_from")
    b.version = 3
    await session.flush()

    await relations.update_relation(
        session, actor=owner, relation_id=edge.id, note="checked", set_note=True
    )
    assert edge.note == "checked"
    assert edge.target_version == 1
    await relations.update_relation(
        session, actor=owner, relation_id=edge.id, refresh_target_version=True
    )
    assert edge.target_version == 3
