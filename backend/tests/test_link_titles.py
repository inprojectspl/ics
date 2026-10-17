"""GET /api/assets/link-titles: titles for `[[ics:...]]` links, per viewer."""

from __future__ import annotations

from app.models import AssetShare
from app.util import now as utc_now
from tests.conftest import login_as, mk_asset, mk_user


async def test_returns_titles_only_for_visible_assets(client, session):
    viewer = await mk_user(session)
    other = await mk_user(session)
    own = await mk_asset(session, viewer, title="My notes")
    shared = await mk_asset(session, other, title="Shared spec")
    hidden = await mk_asset(session, other, title="Secret plan")
    deleted = await mk_asset(session, viewer, title="Gone")
    deleted.deleted_at = utc_now()
    session.add(AssetShare(asset_id=shared.id, user_id=viewer.id, role="viewer"))
    await session.commit()
    await login_as(client, viewer)

    slugs = [own.slug, shared.slug, hidden.slug, deleted.slug, "nosuchslug"]
    r = await client.get("/api/assets/link-titles", params={"slug": slugs})
    assert r.status_code == 200
    assert r.json() == {own.slug: "My notes", shared.slug: "Shared spec"}


async def test_no_slugs_gives_empty_map(client, session):
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)
    r = await client.get("/api/assets/link-titles")
    assert r.status_code == 200
    assert r.json() == {}


async def test_anonymous_gets_401(client):
    r = await client.get("/api/assets/link-titles", params={"slug": ["abc"]})
    assert r.status_code == 401
