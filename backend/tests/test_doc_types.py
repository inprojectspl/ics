"""Doc type vocabulary API (ADR-0015, section 2)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app import json_schema
from app.models import AuditLog
from app.slug import generate_slug
from app.util import now as utc_now
from tests.conftest import login_as, mk_admin, mk_asset, mk_doc_type, mk_user


def _new_key() -> str:
    return f"k_{generate_slug(10)}"


@pytest.mark.asyncio
async def test_non_admin_cannot_create_or_update(client, session):
    user = await mk_user(session)
    doc_type = await mk_doc_type(session)
    await session.commit()
    await login_as(client, user)

    r = await client.post(
        "/api/admin/doc-types",
        json={"key": _new_key(), "label_pl": "Notatka", "label_en": "Note"},
    )
    assert r.status_code == 403
    assert r.json()["code"] == "admin_required"
    r = await client.patch(f"/api/admin/doc-types/{doc_type.key}", json={"archived": True})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_admin_creates_updates_and_archives(client, session):
    admin = await mk_admin(session)
    await session.commit()
    await login_as(client, admin)
    key = _new_key()

    r = await client.post(
        "/api/admin/doc-types",
        json={
            "key": key,
            "label_pl": "Wymagania",
            "label_en": "Requirements",
            "default_review_days": 180,
            "properties_schema": {"type": "object", "properties": {"owner": {"type": "string"}}},
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["archived"] is False

    r = await client.post(
        "/api/admin/doc-types", json={"key": key, "label_pl": "X", "label_en": "X"}
    )
    assert r.status_code == 409
    assert r.json()["code"] == "doc_type_exists"

    r = await client.patch(f"/api/admin/doc-types/{key}", json={"archived": True, "position": 3})
    assert r.status_code == 200
    assert r.json()["archived"] is True

    listed = (await client.get("/api/doc-types")).json()
    assert key not in {d["key"] for d in listed}
    listed = (await client.get("/api/doc-types?include_archived=true")).json()
    row = next(d for d in listed if d["key"] == key)
    assert row["archived"] is True
    assert row["archived_at"] is not None

    actions = (
        await session.execute(
            select(AuditLog.action, AuditLog.payload).where(AuditLog.target == f"doc_type:{key}")
        )
    ).all()
    assert {a for a, _ in actions} == {"doc_type_created", "doc_type_updated"}
    updated = next(p for a, p in actions if a == "doc_type_updated")
    assert sorted(updated["fields"]) == ["archived", "position"]

    r = await client.patch("/api/admin/doc-types/no_such_key", json={"position": 1})
    assert r.status_code == 404
    assert r.json()["code"] == "doc_type_not_found"


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "string"},
        {"type": "object", "properties": {"x": {"type": "whatever"}}},
        {"type": "object", "oneOf": []},
        {"type": "object", "properties": {"x": {"pattern": "("}}},
        {"required": "x"},
    ],
)
@pytest.mark.asyncio
async def test_invalid_schema_is_rejected_with_code(client, session, schema):
    admin = await mk_admin(session)
    doc_type = await mk_doc_type(session)
    await session.commit()
    await login_as(client, admin)

    r = await client.post(
        "/api/admin/doc-types",
        json={"key": _new_key(), "label_pl": "A", "label_en": "A", "properties_schema": schema},
    )
    assert r.status_code == 400
    assert r.json()["code"] == "doc_type_schema_invalid"

    r = await client.patch(
        f"/api/admin/doc-types/{doc_type.key}", json={"properties_schema": schema}
    )
    assert r.status_code == 400
    assert r.json()["code"] == "doc_type_schema_invalid"


@pytest.mark.asyncio
async def test_labels_follow_user_locale_with_english_fallback(client, session):
    user = await mk_user(session, locale="pl")
    doc_type = await mk_doc_type(session)
    await session.commit()
    await login_as(client, user)

    rows = {d["key"]: d for d in (await client.get("/api/doc-types")).json()}
    assert rows[doc_type.key]["label"] == doc_type.label_pl

    user.locale = None
    await session.commit()
    rows = {
        d["key"]: d
        for d in (await client.get("/api/doc-types", headers={"Accept-Language": "en"})).json()
    }
    assert rows[doc_type.key]["label"] == doc_type.label_en


@pytest.mark.asyncio
async def test_archived_type_rejected_in_meta_but_kept_on_asset(client, session):
    owner = await mk_user(session)
    doc_type = await mk_doc_type(session)
    tagged = await mk_asset(session, owner, title="Tagged")
    tagged.doc_type = doc_type.key
    other = await mk_asset(session, owner, title="Other")
    doc_type_key = doc_type.key
    await session.commit()
    doc_type.archived_at = utc_now()
    await session.commit()
    await login_as(client, owner)

    r = await client.patch(f"/api/assets/{other.id}/meta", json={"doc_type": doc_type_key})
    assert r.status_code == 400
    assert r.json()["code"] == "doc_type_unknown"

    # Other edits on the asset that already has the archived type still work.
    r = await client.patch(
        f"/api/assets/{tagged.id}/meta", json={"doc_type": doc_type_key, "language": "en"}
    )
    assert r.status_code == 200
    assert r.json()["doc_type"] == doc_type_key

    meta = (await client.get(f"/api/assets/by-slug/{tagged.slug}/meta")).json()
    assert meta["doc_type"] == doc_type_key


def test_schema_subset_accepts_supported_keywords():
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "tags": {"type": "array", "items": {"type": "string", "maxLength": 5}},
            "level": {"enum": ["low", "high"]},
        },
        "additionalProperties": {"type": "number"},
    }
    json_schema.check_schema(schema)
    assert json_schema.first_error(schema, {"tags": ["a"], "level": "low", "n": 1}, "p") is None
    assert json_schema.first_error(schema, {"tags": ["toolong"]}, "p") == "p.tags[0]"
    assert json_schema.first_error(schema, {"n": "x"}, "p") == "p.n"
    assert json_schema.first_error(schema, {"level": "mid"}, "p") == "p.level"
