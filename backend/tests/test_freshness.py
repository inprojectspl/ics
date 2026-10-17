"""Freshness and flags in asset projections (ADR-0015, section 4)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from app.services.asset_projection import SUMMARY_PREVIEW_CHARS
from app.services.freshness import flags, freshness
from app.util import now as utc_now
from tests.conftest import login_as, mk_asset, mk_md_single, mk_user

NOW = utc_now()


def _doc(*, review_due_at=None, version=1, summary_version=None):
    return SimpleNamespace(
        review_due_at=review_due_at, version=version, summary_version=summary_version
    )


@pytest.mark.parametrize(
    ("review_due_at", "superseded", "expected"),
    [
        (None, False, "current"),
        (NOW + timedelta(days=1), False, "current"),
        (NOW - timedelta(seconds=1), False, "review_overdue"),
        # Superseded wins over an overdue review.
        (NOW - timedelta(days=1), True, "superseded"),
        (None, True, "superseded"),
    ],
)
def test_freshness_rules_and_precedence(review_due_at, superseded, expected):
    doc = _doc(review_due_at=review_due_at)
    assert freshness(doc, NOW, superseded=superseded) == expected


def test_review_due_exactly_now_is_still_current():
    assert freshness(_doc(review_due_at=NOW), NOW) == "current"


@pytest.mark.parametrize(
    ("summary", "version", "summary_version", "expected"),
    [
        (None, 3, 1, []),
        ("About X.", 3, 3, []),
        ("About X.", 3, 2, ["summary_stale"]),
        ("", 3, 1, []),
    ],
)
def test_summary_stale_flag(summary, version, summary_version, expected):
    doc = _doc(version=version, summary_version=summary_version)
    assert flags(doc, summary=summary) == expected


def test_basis_changed_flag_is_independent():
    doc = _doc(version=2, summary_version=1)
    assert flags(doc, summary="s", basis_changed=True) == ["summary_stale", "basis_changed"]


@pytest.mark.asyncio
async def test_meta_reports_overdue_and_full_summary(client, session, fs_storage):
    user, asset = await mk_md_single(client, session)
    asset.review_due_at = utc_now() - timedelta(days=1)
    asset.summary = "x" * 900
    asset.summary_source = "human"
    asset.summary_version = 1
    await session.commit()

    body = (await client.get(f"/api/assets/by-slug/{asset.slug}/meta")).json()
    assert body["freshness"] == "review_overdue"
    assert body["summary"] == "x" * 900
    assert body["summary_source"] == "human"
    assert body["flags"] == []
    assert body["maintainer"]["id"] == str(user.id)
    assert body["content_updated_at"] is not None


@pytest.mark.asyncio
async def test_lists_truncate_summary(client, session, fs_storage):
    user, asset = await mk_md_single(client, session)
    asset.summary = "y" * 900
    asset.summary_version = 1
    await session.commit()

    index = (await client.get("/api/assets/index")).json()["items"]
    row = next(i for i in index if i["id"] == str(asset.id))
    assert len(row["summary"]) == SUMMARY_PREVIEW_CHARS
    assert row["freshness"] == "current"

    listing = (await client.get("/api/assets")).json()["items"]
    row = next(i for i in listing if i["id"] == str(asset.id))
    assert len(row["summary"]) == SUMMARY_PREVIEW_CHARS
    assert row["doc_type"] is None
    assert row["maintainer"]["id"] == str(user.id)


@pytest.mark.asyncio
async def test_summary_stale_after_new_version(client, session, fs_storage):
    _user, asset = await mk_md_single(client, session, content="# One\n")
    asset.summary = "Describes version one."
    asset.summary_version = 1
    await session.commit()

    r = await client.put(f"/api/assets/{asset.id}/content", json={"content": "# Two\n"})
    assert r.status_code == 201

    body = (await client.get(f"/api/assets/by-slug/{asset.slug}/meta")).json()
    assert body["version"] == 2
    assert body["flags"] == ["summary_stale"]


@pytest.mark.asyncio
async def test_every_projection_has_freshness_and_content_updated_at(client, session, fs_storage):
    _user, asset = await mk_md_single(client, session)
    changed = utc_now() - timedelta(days=3)
    asset.content_updated_at = changed
    asset.review_due_at = utc_now() - timedelta(days=1)
    await session.commit()

    index = (await client.get("/api/assets/index")).json()["items"]
    summary = (await client.get(f"/api/assets/by-slug/{asset.slug}/summary")).json()
    meta = (await client.get(f"/api/assets/by-slug/{asset.slug}/meta")).json()
    projections = {
        "index": next(i for i in index if i["id"] == str(asset.id)),
        "summary": summary,
        "meta": meta,
    }
    for name, row in projections.items():
        assert row["freshness"] == "review_overdue", name
        assert row["content_updated_at"].startswith(changed.date().isoformat()), name


@contextmanager
def _count_queries(session) -> Iterator[list[str]]:
    statements: list[str] = []
    engine = session.bind.sync_engine

    def _on_execute(_conn, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", _on_execute)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", _on_execute)


async def _listing_queries(client, session, n: int) -> tuple[int, int]:
    owner = await mk_user(session)
    maintainer = await mk_user(session)
    for i in range(n):
        asset = await mk_asset(session, owner, title=f"Doc {i}")
        asset.summary = f"Summary {i}"
        asset.summary_version = 1
        asset.maintainer_id = maintainer.id if i % 2 else None
    await session.commit()
    await login_as(client, owner)

    with _count_queries(session) as listed:
        r = await client.get("/api/assets")
    assert r.status_code == 200
    assert len(r.json()["items"]) == n
    with _count_queries(session) as indexed:
        r = await client.get("/api/assets/index")
    assert len(r.json()["items"]) == n
    return len(listed), len(indexed)


@pytest.mark.asyncio
async def test_listing_query_count_does_not_grow_with_rows(client, session):
    few = await _listing_queries(client, session, 2)
    await client.post("/api/auth/logout")
    many = await _listing_queries(client, session, 20)
    assert min(few) > 0
    assert few == many
