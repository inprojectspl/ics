"""`freshness=superseded` as a list filter with the ADR-0015 precedence
(superseded > review_overdue > current), and the successor data agents get
in /meta and /index: `superseded_by` (direct successor) and `latest` (the
newest visible document of the `supersedes` chain)."""

from __future__ import annotations

import secrets
import string
from datetime import timedelta

import pytest

from app.models import AssetRelation
from app.util import now as utc_now
from tests.conftest import login_as, mk_asset, mk_doc_type, mk_user, put_blob


def _word() -> str:
    return "zq" + "".join(secrets.choice(string.ascii_lowercase) for _ in range(12))


def _edge(new, old, author) -> AssetRelation:
    """`new supersedes old`, written directly (no visibility check)."""
    return AssetRelation(
        source_asset_id=new.id,
        target_asset_id=old.id,
        relation_type="supersedes",
        target_version=1,
        origin="manual",
        created_by=author.id,
    )


async def _index_slugs(client, **params) -> set[str]:
    r = await client.get("/api/assets/index", params=params)
    assert r.status_code == 200, r.text
    return {i["slug"] for i in r.json()["items"]}


async def _search_slugs(client, **params) -> set[str]:
    r = await client.get("/api/assets/search-mcp", params=params)
    assert r.status_code == 200, r.text
    return {i["slug"] for i in r.json()["items"]}


@pytest.mark.asyncio
async def test_freshness_filter_accepts_superseded_with_precedence(client, session):
    owner = await mk_user(session)
    stranger = await mk_user(session)
    word = _word()
    past = utc_now() - timedelta(days=1)
    old = await mk_asset(session, owner, title=f"Old {word}")
    old.review_due_at = past  # superseded wins over review_overdue
    new = await mk_asset(session, owner, title=f"New {word}")
    overdue = await mk_asset(session, owner, title=f"Overdue {word}")
    overdue.review_due_at = past
    # Superseded only by a document the owner cannot see: still current.
    shadowed = await mk_asset(session, owner, title=f"Shadowed {word}")
    hidden = await mk_asset(session, stranger, title=f"Hidden {word}")
    session.add_all([_edge(new, old, owner), _edge(hidden, shadowed, stranger)])
    await session.commit()
    await login_as(client, owner)

    expected = {
        ("superseded",): {old.slug},
        ("review_overdue",): {overdue.slug},
        ("current",): {new.slug, shadowed.slug},
        ("superseded", "review_overdue"): {old.slug, overdue.slug},
    }
    for values, slugs in expected.items():
        assert await _index_slugs(client, freshness=list(values)) == slugs, values
        assert await _search_slugs(client, q=word, freshness=list(values)) == slugs, values


@pytest.mark.asyncio
async def test_unknown_freshness_value_is_still_rejected(client, session):
    owner = await mk_user(session)
    await session.commit()
    await login_as(client, owner)
    r = await client.get("/api/assets/index", params={"freshness": "stale"})
    assert r.status_code == 422


async def _meta(client, asset) -> dict:
    r = await client.get(f"/api/assets/by-slug/{asset.slug}/meta")
    assert r.status_code == 200, r.text
    return r.json()


def _succ(asset) -> dict:
    return {"id": str(asset.id), "slug": asset.slug, "title": asset.title}


@pytest.mark.asyncio
async def test_chain_reports_direct_successor_and_latest(client, session):
    owner = await mk_user(session)
    stranger = await mk_user(session)
    v1 = await mk_asset(session, owner, title="Spec v1")
    v2 = await mk_asset(session, owner, title="Spec v2")
    v3 = await mk_asset(session, owner, title="Spec v3")
    # A newer version the owner cannot see does not extend their chain.
    v4 = await mk_asset(session, stranger, title="Spec v4")
    session.add_all([_edge(v2, v1, owner), _edge(v3, v2, owner), _edge(v4, v3, stranger)])
    await session.commit()
    await login_as(client, owner)

    index = {i["slug"]: i for i in (await client.get("/api/assets/index")).json()["items"]}
    for asset, successor in ((v1, v2), (v2, v3)):
        for view in (await _meta(client, asset), index[asset.slug]):
            assert view["freshness"] == "superseded"
            assert view["superseded_by"] == _succ(successor)
            assert view["latest"] == v3.slug
    for view in (await _meta(client, v3), index[v3.slug]):
        assert view["freshness"] == "current"
        assert view["superseded_by"] is None
        assert view["latest"] is None
    assert v4.slug not in str(index)


@pytest.mark.asyncio
async def test_latest_moves_with_the_end_of_the_chain(client, session):
    owner = await mk_user(session)
    v1 = await mk_asset(session, owner, title="Plan v1")
    v2 = await mk_asset(session, owner, title="Plan v2")
    v3 = await mk_asset(session, owner, title="Plan v3")
    session.add_all([_edge(v2, v1, owner), _edge(v3, v2, owner)])
    await session.commit()
    await login_as(client, owner)

    before = await client.get(f"/api/assets/by-slug/{v1.slug}/meta")
    # The ETag moves when the end of the chain moves, not only the direct successor.
    v4 = await mk_asset(session, owner, title="Plan v4")
    session.add(_edge(v4, v3, owner))
    await session.commit()
    after = await client.get(f"/api/assets/by-slug/{v1.slug}/meta")
    assert after.json()["latest"] == v4.slug
    assert after.json()["superseded_by"] == _succ(v2)
    assert before.headers["etag"] != after.headers["etag"]


@pytest.mark.asyncio
async def test_latest_is_cycle_safe(client, session):
    owner = await mk_user(session)
    a = await mk_asset(session, owner, title="A")
    b = await mk_asset(session, owner, title="B")
    # A cycle can only appear through edges written past the cycle check.
    session.add_all([_edge(a, b, owner), _edge(b, a, owner)])
    await session.commit()
    await login_as(client, owner)

    meta_a, meta_b = await _meta(client, a), await _meta(client, b)
    assert meta_a["superseded_by"]["slug"] == b.slug
    assert meta_a["latest"] == b.slug
    assert meta_b["latest"] == a.slug


@pytest.mark.asyncio
async def test_agent_reads_carry_latest_and_read_size(client, session, fs_storage):
    """The read, the outline and search give `latest` too, so an agent that
    starts from any of them lands on the end of the chain (v3), not on the
    superseded direct successor (v2)."""
    owner = await mk_user(session)
    doc_type = await mk_doc_type(session)
    word = _word()
    v1 = await mk_asset(session, owner, title=f"Spec v1 {word}")
    v2 = await mk_asset(session, owner, title=f"Spec v2 {word}")
    v3 = await mk_asset(session, owner, title=f"Spec v3 {word}")
    v1.doc_type = doc_type.key
    v1.read_tokens = 1484
    v1.outline_status, v1.outline_version = "fresh", v1.version
    v1.outline_json = {"headings": []}
    session.add_all([_edge(v2, v1, owner), _edge(v3, v2, owner)])
    await session.commit()
    for asset in (v1, v3):
        await put_blob(asset, "doc.md", b"# Spec\n")
    await login_as(client, owner)

    read = (await client.get(f"/api/assets/by-slug/{v1.slug}/file-mcp")).json()
    assert read["superseded_by"] == _succ(v2)
    assert read["latest"] == v3.slug
    assert (await client.get(f"/api/assets/by-slug/{v3.slug}/file-mcp")).json()["latest"] is None

    outline = (await client.get(f"/api/assets/by-slug/{v1.slug}/outline")).json()
    assert outline["latest"] == v3.slug
    assert outline["doc_type"] == doc_type.key
    assert outline["estimated_tokens"] == 1484

    r = await client.get("/api/assets/search-mcp", params={"q": word})
    hits = {i["slug"]: i for i in r.json()["items"]}
    assert hits[v1.slug]["latest"] == hits[v2.slug]["latest"] == v3.slug
    assert hits[v3.slug]["latest"] is None
    assert hits[v1.slug]["estimated_tokens"] == 1484
