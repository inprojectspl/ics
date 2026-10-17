"""PATCH /api/assets/{id}/meta (ADR-0015)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models import AssetShare, AuditLog
from app.oauth import tokens as tokens_mod
from app.util import now as utc_now
from tests.conftest import login_as, mk_asset, mk_doc_type, mk_user

_AUDIENCE = "https://ics-test.example/mcp"


def _bearer(user, monkeypatch) -> dict[str, str]:
    settings = get_settings()
    monkeypatch.setattr(settings, "mcp_resource_uri", _AUDIENCE)
    monkeypatch.setattr(settings, "debug", True)
    token, _jti = tokens_mod.sign_access_jwt(
        settings=settings,
        user=user,
        client_id_external="ics-mcp-stdio",
        scopes=["ics"],
        audience=_AUDIENCE,
    )
    return {"Authorization": f"Bearer {token}"}


async def _shared_asset(session, role: str):
    owner = await mk_user(session)
    other = await mk_user(session)
    asset = await mk_asset(session, owner)
    session.add(AssetShare(asset_id=asset.id, user_id=other.id, role=role))
    await session.commit()
    return asset, other


@pytest.mark.asyncio
async def test_viewer_cannot_patch_meta(client, session):
    asset, viewer = await _shared_asset(session, "viewer")
    await login_as(client, viewer)
    r = await client.patch(f"/api/assets/{asset.id}/meta", json={"summary": "x"})
    assert r.status_code == 404
    assert r.json()["code"] == "asset_not_found"


@pytest.mark.asyncio
async def test_editor_updates_meta_and_audit_lists_field_names(client, session):
    asset, editor = await _shared_asset(session, "editor")
    doc_type = await mk_doc_type(session, default_review_days=30)
    await session.commit()
    await login_as(client, editor)

    r = await client.patch(
        f"/api/assets/{asset.id}/meta",
        json={
            "summary": "  What the note is for.  ",
            "doc_type": doc_type.key,
            "maintainer_id": str(editor.id),
            "language": "pl",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"] == "What the note is for."
    assert body["summary_source"] == "human"
    assert body["summary_version"] == asset.version
    assert body["doc_type"] == doc_type.key
    assert body["maintainer"]["id"] == str(editor.id)
    assert body["language"] == "pl"
    # A new type fills an empty review date from default_review_days.
    assert body["review_due_at"] is not None
    assert body["freshness"] == "current"

    entry = (
        await session.execute(
            select(AuditLog).where(
                AuditLog.action == "asset_metadata_updated",
                AuditLog.target == f"asset:{asset.id}",
            )
        )
    ).scalar_one()
    assert sorted(entry.payload["fields"]) == sorted(
        ["summary", "doc_type", "maintainer_id", "language", "review_due_at"]
    )
    assert "What the note" not in str(entry.payload)


@pytest.mark.asyncio
async def test_every_field_is_written_and_audited(client, session):
    owner = await mk_user(session)
    maintainer = await mk_user(session)
    asset = await mk_asset(session, owner)
    session.add(AssetShare(asset_id=asset.id, user_id=maintainer.id, role="viewer"))
    doc_type = await mk_doc_type(
        session,
        properties_schema={"type": "object", "properties": {"budget": {"type": "integer"}}},
    )
    await session.commit()
    await login_as(client, owner)
    due = (utc_now() + timedelta(days=10)).replace(microsecond=0)

    r = await client.patch(
        f"/api/assets/{asset.id}/meta",
        json={
            "summary": "Every field at once.",
            "doc_type": doc_type.key,
            "maintainer_id": str(maintainer.id),
            "review_due_at": due.isoformat(),
            "language": "en",
            "properties": {"budget": 7},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"] == "Every field at once."
    assert body["doc_type"] == doc_type.key
    assert body["maintainer_id"] == str(maintainer.id)
    assert body["review_due_at"] == due.isoformat()
    assert body["language"] == "en"
    assert body["properties"] == {"budget": 7}

    # A reload reads /meta: every field the write returned must be there too.
    r = await client.get(f"/api/assets/by-slug/{asset.slug}/meta")
    assert r.status_code == 200
    reloaded = r.json()
    for key in (
        "summary",
        "doc_type",
        "maintainer",
        "maintainer_id",
        "reviewed_at",
        "reviewed_by",
        "language",
        "properties",
        "summary_version",
    ):
        assert reloaded[key] == body[key], key
    assert datetime.fromisoformat(reloaded["review_due_at"]) == due

    entry = (
        await session.execute(
            select(AuditLog).where(
                AuditLog.action == "asset_metadata_updated",
                AuditLog.target == f"asset:{asset.id}",
            )
        )
    ).scalar_one()
    assert sorted(entry.payload["fields"]) == sorted(
        ["summary", "doc_type", "maintainer_id", "review_due_at", "language", "properties"]
    )


@pytest.mark.asyncio
async def test_explicit_review_date_wins_over_type_default(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    doc_type = await mk_doc_type(session, default_review_days=30)
    await session.commit()
    await login_as(client, owner)
    due = utc_now() - timedelta(days=2)

    r = await client.patch(
        f"/api/assets/{asset.id}/meta",
        json={"doc_type": doc_type.key, "review_due_at": due.isoformat()},
    )
    assert r.status_code == 200
    assert r.json()["freshness"] == "review_overdue"


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"summary": "x" * 1001}, "summary"),
        ({"language": "polish please"}, "language"),
        ({"maintainer_id": "00000000-0000-0000-0000-000000000001"}, "maintainer_id"),
        ({"properties": {"blob": "x" * 17_000}}, "properties"),
    ],
)
@pytest.mark.asyncio
async def test_metadata_invalid_names_the_field(client, session, payload, field):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await login_as(client, owner)
    r = await client.patch(f"/api/assets/{asset.id}/meta", json=payload)
    assert r.status_code == 400
    assert r.json()["code"] == "metadata_invalid"
    assert r.json()["field"] == field


@pytest.mark.asyncio
async def test_properties_validated_against_doc_type_schema(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    doc_type = await mk_doc_type(
        session,
        properties_schema={
            "type": "object",
            "properties": {"budget": {"type": "integer", "minimum": 0}},
            "required": ["budget"],
            "additionalProperties": False,
        },
    )
    await session.commit()
    await login_as(client, owner)
    url = f"/api/assets/{asset.id}/meta"

    r = await client.patch(url, json={"doc_type": doc_type.key, "properties": {"budget": "a"}})
    assert r.status_code == 400
    assert r.json()["field"] == "properties.budget"

    r = await client.patch(url, json={"doc_type": doc_type.key, "properties": {}})
    assert r.json()["field"] == "properties.budget"

    r = await client.patch(url, json={"doc_type": doc_type.key, "properties": {"budget": 5}})
    assert r.status_code == 200
    assert r.json()["properties"] == {"budget": 5}

    r = await client.patch(url, json={"properties": {"budget": 5, "extra": 1}})
    assert r.json()["field"] == "properties.extra"


@pytest.mark.asyncio
async def test_unknown_doc_type(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await login_as(client, owner)
    r = await client.patch(f"/api/assets/{asset.id}/meta", json={"doc_type": "no_such_type"})
    assert r.status_code == 400
    assert r.json()["code"] == "doc_type_unknown"


@pytest.mark.asyncio
async def test_summary_source_agent_via_bearer(client, session, monkeypatch):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()

    r = await client.patch(
        f"/api/assets/{asset.id}/meta",
        json={"summary": "Written by an agent."},
        headers=_bearer(owner, monkeypatch),
    )
    assert r.status_code == 200, r.text
    assert r.json()["summary_source"] == "agent"
    entry = (
        await session.execute(
            select(AuditLog).where(
                AuditLog.action == "asset_metadata_updated",
                AuditLog.target == f"asset:{asset.id}",
            )
        )
    ).scalar_one()
    assert entry.transport == "bearer"


@pytest.mark.asyncio
async def test_clearing_summary_clears_source(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await login_as(client, owner)
    url = f"/api/assets/{asset.id}/meta"
    await client.patch(url, json={"summary": "Something."})
    r = await client.patch(url, json={"summary": None})
    assert r.json()["summary"] is None
    assert r.json()["summary_source"] is None
    assert r.json()["summary_version"] is None


@pytest.mark.asyncio
async def test_no_change_writes_no_audit(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await login_as(client, owner)
    r = await client.patch(f"/api/assets/{asset.id}/meta", json={"language": None})
    assert r.status_code == 200
    count = (
        await session.execute(
            select(AuditLog).where(
                AuditLog.action == "asset_metadata_updated",
                AuditLog.target == f"asset:{asset.id}",
            )
        )
    ).all()
    assert count == []


@pytest.mark.asyncio
async def test_meta_read_carries_review_confirmation(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await login_as(client, owner)

    r = await client.post(f"/api/assets/{asset.id}/reviewed")
    assert r.status_code == 200, r.text
    r = await client.get(f"/api/assets/by-slug/{asset.slug}/meta")
    assert r.status_code == 200
    body = r.json()
    assert body["reviewed_by"] == str(owner.id)
    assert body["reviewed_at"] is not None
    assert body["properties"] == {}
