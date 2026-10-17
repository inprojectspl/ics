"""Context pack with a `supersedes` chain A <- B <- C (ADR-0019): every
document stays in the response, the chain collapses into its newest visible
document, and a successor the caller cannot see is never revealed."""

from __future__ import annotations

import pytest

from tests.conftest import login_as, mk_asset, mk_user
from tests.test_context_pack import _edge, _link, _pack, _slugs, _wp


@pytest.mark.asyncio
async def test_chain_collapses_into_its_newest_document(client, session):
    owner = await mk_user(session)
    wp = _wp()
    a = await mk_asset(session, owner, title="Spec v1")
    b = await mk_asset(session, owner, title="Spec v2")
    c = await mk_asset(session, owner, title="Spec v3")
    session.add_all(
        [
            _link(a, wp, required=True),
            _edge(b, a, "supersedes", owner),
            _edge(c, b, "supersedes", owner),
        ]
    )
    await session.commit()
    await login_as(client, owner)

    body = await _pack(client, wp)

    assert _slugs(body)[0] == c.slug
    assert set(_slugs(body)) == {a.slug, b.slug, c.slug}
    newest, *collapsed = body["documents"]
    assert newest["required"] is True
    assert "collapsed" not in newest
    assert {(d["slug"], d["superseded_by"], d["collapsed"]) for d in collapsed} == {
        (b.slug, c.slug, True),
        (a.slug, c.slug, True),
    }
    assert next(d for d in collapsed if d["slug"] == a.slug)["required"] is True


@pytest.mark.asyncio
async def test_chain_stops_before_a_successor_the_caller_cannot_see(client, session):
    owner = await mk_user(session)
    stranger = await mk_user(session)
    wp = _wp()
    a = await mk_asset(session, owner, title="Spec v1")
    b = await mk_asset(session, owner, title="Spec v2")
    hidden = await mk_asset(session, stranger, title="Secret v3")
    session.add_all(
        [
            _link(a, wp, required=True),
            _edge(b, a, "supersedes", owner),
            _edge(hidden, b, "supersedes", stranger),
        ]
    )
    await session.commit()
    await login_as(client, owner)

    body = await _pack(client, wp)

    assert _slugs(body) == [b.slug, a.slug]
    assert hidden.slug not in str(body)
    assert "Secret" not in str(body)
    assert body["documents"][1]["superseded_by"] == b.slug
