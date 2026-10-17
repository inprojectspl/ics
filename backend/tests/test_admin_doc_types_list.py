"""Admin list of document types and archiving through PATCH (ADR-0015)."""

from __future__ import annotations

from sqlalchemy import select

from app.models import DocType
from tests.conftest import login_as, mk_admin, mk_doc_type, mk_user


async def test_admin_lists_all_types_with_both_labels(client, session):
    admin = await mk_admin(session)
    active = await mk_doc_type(session)
    archived = await mk_doc_type(session, archived=True)
    await session.commit()
    await login_as(client, admin)

    r = await client.get("/api/admin/doc-types")
    assert r.status_code == 200
    rows = {row["key"]: row for row in r.json()}
    assert rows[active.key]["archived"] is False
    assert rows[active.key]["archived_at"] is None
    assert rows[archived.key]["archived"] is True
    assert rows[archived.key]["archived_at"] is not None
    for doc_type in (active, archived):
        assert rows[doc_type.key]["label_pl"] == doc_type.label_pl
        assert rows[doc_type.key]["label_en"] == doc_type.label_en


async def test_normal_user_gets_403(client, session):
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)

    r = await client.get("/api/admin/doc-types")
    assert r.status_code == 403
    assert r.json()["code"] == "admin_required"


async def test_patch_archived_sets_and_clears_archived_at(client, session):
    admin = await mk_admin(session)
    doc_type = await mk_doc_type(session)
    await session.commit()
    await login_as(client, admin)

    async def _archived_at():
        return await session.scalar(
            select(DocType.archived_at)
            .where(DocType.key == doc_type.key)
            .execution_options(populate_existing=True)
        )

    r = await client.patch(f"/api/admin/doc-types/{doc_type.key}", json={"archived": True})
    assert r.status_code == 200
    assert r.json()["archived"] is True
    assert await _archived_at() is not None

    r = await client.patch(f"/api/admin/doc-types/{doc_type.key}", json={"archived": False})
    assert r.status_code == 200
    assert r.json()["archived"] is False
    assert await _archived_at() is None
