"""POST /api/assets/{id}/reviewed: "still current" (ADR-0015)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.constants import AUDIT_ACTIONS
from app.models import AssetShare, AuditLog
from app.util import now as utc_now
from tests.conftest import login_as, mk_asset, mk_doc_type, mk_user


@pytest.mark.asyncio
async def test_confirm_moves_overdue_document_back_to_current(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    doc_type = await mk_doc_type(session, default_review_days=90)
    asset.doc_type = doc_type.key
    asset.review_due_at = utc_now() - timedelta(days=3)
    await session.commit()
    await login_as(client, owner)

    meta = (await client.get(f"/api/assets/by-slug/{asset.slug}/meta")).json()
    assert meta["freshness"] == "review_overdue"

    r = await client.post(f"/api/assets/{asset.id}/reviewed")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["freshness"] == "current"
    assert body["reviewed_by"] == str(owner.id)
    assert body["reviewed_at"] is not None
    due = body["review_due_at"]
    assert due is not None and due > (utc_now() + timedelta(days=89)).isoformat()

    meta = (await client.get(f"/api/assets/by-slug/{asset.slug}/meta")).json()
    assert meta["freshness"] == "current"

    entry = (
        await session.execute(
            select(AuditLog).where(
                AuditLog.action == "asset_reviewed", AuditLog.target == f"asset:{asset.id}"
            )
        )
    ).scalar_one()
    assert entry.action in AUDIT_ACTIONS


@pytest.mark.asyncio
async def test_confirm_without_review_period_clears_due_date(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    asset.review_due_at = utc_now() - timedelta(days=1)
    await session.commit()
    await login_as(client, owner)

    r = await client.post(f"/api/assets/{asset.id}/reviewed")
    assert r.status_code == 200
    assert r.json()["review_due_at"] is None
    assert r.json()["freshness"] == "current"


@pytest.mark.asyncio
async def test_viewer_cannot_confirm(client, session):
    owner = await mk_user(session)
    viewer = await mk_user(session)
    asset = await mk_asset(session, owner)
    session.add(AssetShare(asset_id=asset.id, user_id=viewer.id, role="viewer"))
    await session.commit()
    await login_as(client, viewer)

    r = await client.post(f"/api/assets/{asset.id}/reviewed")
    assert r.status_code == 404
    assert r.json()["code"] == "asset_not_found"
