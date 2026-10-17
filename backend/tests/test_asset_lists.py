"""Asset lists stay light and paginated: no note bodies in the query and a
bounded page per request."""

from __future__ import annotations

import pytest
from sqlalchemy import event

from app.models import AssetShare
from tests.conftest import login_as, mk_asset, mk_user


@pytest.mark.asyncio
async def test_list_query_does_not_select_note_text(client, session):
    user = await mk_user(session)
    asset = await mk_asset(session, user)
    asset.search_content = "full body of the note " * 100
    await session.commit()
    await login_as(client, user)

    statements: list[str] = []

    def _capture(_conn, _cursor, statement, *_args):
        statements.append(statement)

    engine = session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", _capture)
    try:
        r = await client.get("/api/assets")
    finally:
        event.remove(engine, "before_cursor_execute", _capture)

    assert r.status_code == 200
    assert [a["id"] for a in r.json()["items"]] == [str(asset.id)]
    assert statements
    assert not [s for s in statements if "search_content" in s or "search_tsv" in s]


@pytest.mark.asyncio
async def test_asset_list_pages_without_overlap(client, session):
    user = await mk_user(session)
    ids = {str((await mk_asset(session, user, title=f"doc {i}")).id) for i in range(5)}
    await session.commit()
    await login_as(client, user)

    seen: list[str] = []
    for page in (1, 2, 3):
        r = await client.get("/api/assets", params={"page": page, "page_size": 2})
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 5
        assert body["page"] == page
        assert len(body["items"]) == (2 if page < 3 else 1)
        seen += [a["id"] for a in body["items"]]

    assert len(seen) == 5
    assert set(seen) == ids


@pytest.mark.asyncio
async def test_asset_list_rejects_oversized_page(client, session):
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)

    r = await client.get("/api/assets", params={"page_size": 1000})

    assert r.status_code == 422


@pytest.mark.asyncio
async def test_shared_with_me_is_paginated(client, session):
    owner = await mk_user(session)
    reader = await mk_user(session)
    assets = [await mk_asset(session, owner, title=f"shared {i}") for i in range(3)]
    for a in assets:
        session.add(AssetShare(asset_id=a.id, user_id=reader.id, role="viewer"))
    await session.commit()
    await login_as(client, reader)

    first = (await client.get("/api/shared-with-me", params={"page_size": 2})).json()
    second = (await client.get("/api/shared-with-me", params={"page": 2, "page_size": 2})).json()

    assert first["total"] == second["total"] == 3
    got = [a["id"] for a in first["standalone_assets"] + second["standalone_assets"]]
    assert sorted(got) == sorted(str(a.id) for a in assets)
