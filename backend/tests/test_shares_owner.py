"""Tests for `routes/shares/owner.py`: listing shares of an asset."""

from __future__ import annotations

import pytest

from tests.conftest import login_as as _login
from tests.conftest import mk_asset, mk_user


@pytest.mark.asyncio
async def test_list_shares_for_asset_includes_revoked_with_timestamp(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)

    r1 = await client.post(
        f"/api/assets/{asset.id}/shares",
        json={"mode": "public"},
    )
    r2 = await client.post(
        f"/api/assets/{asset.id}/shares",
        json={"mode": "public"},
    )
    s1_id = r1.json()["id"]

    await client.delete(f"/api/shares/{s1_id}")

    listing = await client.get(f"/api/assets/{asset.id}/shares")
    assert listing.status_code == 200
    by_id = {s["id"]: s for s in listing.json()}
    assert by_id.keys() == {s1_id, r2.json()["id"]}
    assert by_id[s1_id]["revoked_at"] is not None
    assert by_id[r2.json()["id"]]["revoked_at"] is None
