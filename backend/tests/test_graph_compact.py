"""Compact graph shape for agents (ADR-0016, section 10): nodes keyed by slug
without nulls or defaults, edges as triples, content links folded into the
typed edge they repeat, `direction` on the neighbourhood and `end_line` plus
optional edges on the outline."""

from __future__ import annotations

import json

import pytest

from app.models import AssetRelation
from tests.conftest import login_as, mk_asset, mk_user


def _rel(source, target, relation_type="derived_from", **kw) -> AssetRelation:
    return AssetRelation(
        source_asset_id=source.id,
        target_asset_id=target.id,
        relation_type=relation_type,
        target_version=1,
        origin=kw.pop("origin", "manual"),
        **kw,
    )


async def _chain(session):
    """d -> a -> b -> c along derived_from, b superseded by e."""
    owner = await mk_user(session)
    a, b, c, d, e = [await mk_asset(session, owner, title=t) for t in "abcde"]
    a.summary = "x" * 300
    session.add_all([_rel(a, b), _rel(b, c), _rel(d, a), _rel(e, b, "supersedes")])
    await session.commit()
    return owner, a, b, c, d, e


@pytest.mark.asyncio
async def test_neighbourhood_compact_follows_direction(client, session):
    owner, a, b, c, d, e = await _chain(session)
    await login_as(client, owner)
    url = f"/api/assets/by-slug/{a.slug}/neighbourhood"

    up = (await client.get(url, params={"shape": "compact", "depth": 3, "direction": "out"})).json()
    assert list(up["nodes"]) == [a.slug, b.slug, c.slug]
    assert up["root"] == a.slug and up["direction"] == "out"
    assert up["nodes"][a.slug]["depth"] == 0
    assert len(up["nodes"][a.slug]["summary"]) == 200
    assert up["nodes"][b.slug]["superseded_by"] == e.slug
    assert up["nodes"][b.slug]["freshness"] == "superseded"
    assert "freshness" not in up["nodes"][c.slug]
    assert sorted(up["edges"]) == sorted(
        [[a.slug, "derived_from", b.slug], [b.slug, "derived_from", c.slug]]
    )
    assert "truncated" not in up and ":null" not in json.dumps(up, separators=(",", ":"))

    down = (
        await client.get(url, params={"shape": "compact", "depth": 3, "direction": "in"})
    ).json()
    assert list(down["nodes"]) == [a.slug, d.slug]

    # The web client's default shape is unchanged.
    full = (await client.get(url)).json()
    assert {n["slug"] for n in full["nodes"]} == {a.slug, b.slug, d.slug}
    assert "source_id" in full["edges"][0]


@pytest.mark.asyncio
async def test_relations_compact_carries_edge_ids_and_folds_content_links(client, session):
    owner = await mk_user(session)
    a, b, c = [await mk_asset(session, owner, title=t) for t in "abc"]
    typed = _rel(a, b, "depends_on", note="API contract")
    session.add_all(
        [
            typed,
            _rel(a, b, "references", origin="extracted"),
            _rel(c, a, "references", origin="extracted"),
        ]
    )
    await session.commit()
    await login_as(client, owner)

    body = (
        await client.get(f"/api/assets/by-slug/{a.slug}/relations", params={"shape": "compact"})
    ).json()
    assert body["asset"] == a.slug
    assert set(body["nodes"]) == {b.slug, c.slug}
    # Outgoing first; a content link alone is kept, one next to a typed edge is not.
    assert body["edges"][0] == [
        a.slug,
        "depends_on",
        b.slug,
        {"id": str(typed.id), "note": "API contract"},
    ]
    assert [e[:3] for e in body["edges"][1:]] == [[c.slug, "references", a.slug]]


@pytest.mark.asyncio
async def test_outline_end_lines_and_optional_compact_edges(client, session, fs_storage):
    owner = await mk_user(session)
    doc = await mk_asset(session, owner, title="Spec")
    goals = await mk_asset(session, owner, title="Goals")
    doc.outline_status = "fresh"
    doc.outline_version = doc.version
    doc.outline_json = {
        "kind": "md_single",
        "line_count": 9,
        "headings": [
            {"level": 1, "text": "Spec", "line": 1, "anchor": "spec"},
            {"level": 2, "text": "Scope", "line": 3, "anchor": "scope"},
            {"level": 2, "text": "Errors", "line": 6, "anchor": "errors"},
        ],
    }
    session.add(_rel(doc, goals, target_anchor="why"))
    await session.commit()
    await login_as(client, owner)
    url = f"/api/assets/by-slug/{doc.slug}/outline"

    bare = (await client.get(url, params={"edges": "false"})).json()
    assert "edges" not in bare
    assert [h["end_line"] for h in bare["headings"]] == [9, 5, 9]

    compact = (await client.get(url, params={"shape": "compact"})).json()
    assert compact["nodes"] == {goals.slug: {"title": "Goals"}}
    assert compact["edges"] == [[doc.slug, "derived_from", goals.slug, {"target_anchor": "why"}]]

    full = (await client.get(url)).json()
    assert full["edges"][0]["target_slug"] == goals.slug
