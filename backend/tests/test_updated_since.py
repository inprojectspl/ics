"""`updated_since` and "last changed" ordering follow the content change time
(`content_updated_at`); `touched_since` keeps the row-update meaning.

A tag change moves only `updated_at`, so it must not count as a change.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.conftest import login_as, mk_asset, mk_user


async def _retagged_and_edited(client, session):
    """`retagged`: content written two days ago, tags changed just now through
    the API. `edited`: content written an hour ago, no metadata change since."""
    user = await mk_user(session)
    retagged = await mk_asset(session, user, title="Retagged")
    edited = await mk_asset(session, user, title="Edited")
    now = datetime.now(UTC)
    # Explicit `updated_at` values, so no clock comparison between the test
    # process and the database decides the outcome.
    retagged.content_updated_at = retagged.updated_at = now - timedelta(days=2)
    edited.content_updated_at = edited.updated_at = now - timedelta(hours=1)
    await session.commit()
    await login_as(client, user)

    r = await client.put(f"/api/assets/{retagged.id}/tags", json={"tags": ["later-tag"]})
    assert r.status_code == 200
    return retagged, edited, now


async def _index_ids(client, **params) -> set[str]:
    r = await client.get("/api/assets/index", params=params)
    assert r.status_code == 200
    return {it["id"] for it in r.json()["items"]}


@pytest.mark.asyncio
async def test_updated_since_ignores_a_tag_only_change(client, session):
    retagged, edited, now = await _retagged_and_edited(client, session)
    since = (now - timedelta(days=1)).isoformat()

    ids = await _index_ids(client, updated_since=since)
    assert str(edited.id) in ids
    assert str(retagged.id) not in ids


@pytest.mark.asyncio
async def test_touched_since_includes_a_tag_only_change(client, session):
    retagged, edited, now = await _retagged_and_edited(client, session)

    ids = await _index_ids(client, touched_since=(now - timedelta(days=1)).isoformat())
    assert {str(retagged.id), str(edited.id)} <= ids
    # After the tag write only the retagged row was touched.
    ids = await _index_ids(client, touched_since=(now - timedelta(minutes=10)).isoformat())
    assert str(retagged.id) in ids
    assert str(edited.id) not in ids


@pytest.mark.asyncio
@pytest.mark.parametrize("order", [None, "desc"])
async def test_last_change_sort_ignores_metadata_only_updates(client, session, order):
    retagged, edited, _ = await _retagged_and_edited(client, session)
    params = {"sort": "updated"} | ({"order": order} if order else {})

    r = await client.get("/api/assets", params=params)
    assert r.status_code == 200
    ids = [it["id"] for it in r.json()["items"]]
    assert ids.index(str(edited.id)) < ids.index(str(retagged.id))

    r = await client.get("/api/assets", params={"sort": "updated", "order": "asc"})
    ids = [it["id"] for it in r.json()["items"]]
    assert ids.index(str(retagged.id)) < ids.index(str(edited.id))
