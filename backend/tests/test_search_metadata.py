"""Weighted search vector and metadata filters (ADR-0015, section 5)."""

from __future__ import annotations

import secrets
import string
from datetime import timedelta

from app.util import now as utc_now
from tests.conftest import login_as, mk_asset, mk_doc_type, mk_user


def _word() -> str:
    # Letters only: the 'simple' parser keeps it one plain lexeme, and the
    # randomness keeps tests sharing a worker database apart.
    return "zq" + "".join(secrets.choice(string.ascii_lowercase) for _ in range(12))


async def _search(client, **params) -> list[str]:
    r = await client.get("/api/assets/search-mcp", params=params)
    assert r.status_code == 200, r.text
    return [item["slug"] for item in r.json()["items"]]


async def test_summary_match_ranks_above_content_match(client, session):
    user = await mk_user(session)
    word = _word()
    filler = " ".join(["lorem"] * 50)
    in_content = await mk_asset(session, user, title="Alpha")
    in_content.search_content = f"{filler} {word} {filler}"
    in_summary = await mk_asset(session, user, title="Beta")
    in_summary.summary = f"About {word}."
    in_summary.search_content = filler
    await session.commit()
    await login_as(client, user)

    assert await _search(client, q=word) == [in_summary.slug, in_content.slug]


async def test_tags_are_searchable_and_filter_search(client, session):
    user = await mk_user(session)
    word, tag = _word(), _word()
    tagged = await mk_asset(session, user, title=f"One {word}")
    tagged.tags = [tag]
    untagged = await mk_asset(session, user, title=f"Two {word}")
    await session.commit()
    await login_as(client, user)

    assert set(await _search(client, q=word)) == {tagged.slug, untagged.slug}
    assert await _search(client, q=word, tag=[tag]) == [tagged.slug]
    # The tag itself is in the vector.
    assert await _search(client, q=tag) == [tagged.slug]


async def test_freshness_review_overdue_returns_only_overdue(client, session):
    user = await mk_user(session)
    word = _word()
    now = utc_now()
    overdue = await mk_asset(session, user, title=f"Old {word}")
    overdue.review_due_at = now - timedelta(days=1)
    upcoming = await mk_asset(session, user, title=f"Soon {word}")
    upcoming.review_due_at = now + timedelta(days=30)
    undated = await mk_asset(session, user, title=f"Undated {word}")
    await session.commit()
    await login_as(client, user)

    assert await _search(client, q=word, freshness=["review_overdue"]) == [overdue.slug]
    assert set(await _search(client, q=word, freshness=["current"])) == {
        upcoming.slug,
        undated.slug,
    }

    r = await client.get("/api/assets/index", params={"q": word, "freshness": ["review_overdue"]})
    assert r.status_code == 200
    assert [i["slug"] for i in r.json()["items"]] == [overdue.slug]

    r = await client.get("/api/assets/search-mcp", params={"q": word, "freshness": "stale"})
    assert r.status_code == 422


async def test_index_filters_by_doc_type_tag_and_maintainer(client, session):
    user = await mk_user(session)
    other = await mk_user(session)
    doc_type = await mk_doc_type(session)
    word, tag = _word(), _word()
    typed = await mk_asset(session, user, title=f"Typed {word}")
    typed.doc_type = doc_type.key
    typed.tags = [tag]
    maintained = await mk_asset(session, user, title=f"Kept {word}")
    maintained.maintainer_id = other.id
    await session.commit()
    await login_as(client, user)

    async def _index(**params) -> set[str]:
        r = await client.get("/api/assets/index", params={"q": word, **params})
        assert r.status_code == 200, r.text
        return {i["slug"] for i in r.json()["items"]}

    assert await _index() == {typed.slug, maintained.slug}
    assert await _index(doc_type=[doc_type.key]) == {typed.slug}
    assert await _index(tag=[tag]) == {typed.slug}
    assert await _index(maintainer=str(other.id)) == {maintained.slug}
    assert set(await _search(client, q=word, doc_type=[doc_type.key])) == {typed.slug}


async def test_unknown_doc_type_filter_is_refused_with_active_keys(client, session):
    user = await mk_user(session)
    active = await mk_doc_type(session)
    archived = await mk_doc_type(session, archived=True)
    word = _word()
    kept = await mk_asset(session, user, title=f"Archived {word}")
    kept.doc_type = archived.key
    await session.commit()
    await login_as(client, user)

    missing = f"nope{secrets.token_hex(4)}"
    for path, params in (
        ("/api/assets/index", {"doc_type": [active.key, missing]}),
        ("/api/assets/search-mcp", {"q": word, "doc_type": [missing]}),
    ):
        r = await client.get(path, params=params)
        assert r.status_code == 400, r.text
        body = r.json()
        assert body["code"] == "doc_type_filter_unknown"
        assert body["field"] == "doc_type"
        assert active.key in body["allowed"]
        assert archived.key not in body["allowed"]

    # An archived type still filters: assets keep it.
    assert await _search(client, q=word, doc_type=[archived.key]) == [kept.slug]
    r = await client.get("/api/assets/index", params={"q": word, "doc_type": [archived.key]})
    assert [i["slug"] for i in r.json()["items"]] == [kept.slug]
