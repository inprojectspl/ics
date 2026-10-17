"""Relations from HTML bundle links (ADR-0016, section 4): root-relative and
absolute links to ICS documents become `references` edges, links between the
bundle's own pages do not."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.bundle_scan import link_hrefs
from app.models import AssetRelation
from app.services.relation_extraction import _absolute_links
from tests.conftest import login_as, mk_asset, mk_user


async def _upload_bundle(client, pages: dict[str, str]) -> str:
    r = await client.post(
        "/api/assets/html",
        files=[("files", (name, html.encode(), "text/html")) for name, html in pages.items()],
        data={"paths": list(pages)},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _targets(session, source_id: str) -> list[UUID]:
    rows = await session.scalars(
        select(AssetRelation)
        .where(AssetRelation.source_asset_id == UUID(source_id))
        .execution_options(populate_existing=True)
    )
    return [e.target_asset_id for e in rows.all() if e.origin == "extracted"]


async def test_root_relative_link_creates_a_references_edge(client, session, fs_storage):
    author = await mk_user(session)
    target = await mk_asset(session, author, title="Target")
    await session.commit()
    await login_as(client, author)

    html = f'<!doctype html><html><body><a href="/v/{target.slug}">spec</a></body></html>'
    source_id = await _upload_bundle(client, {"index.html": html})

    rows = (
        await session.scalars(
            select(AssetRelation).where(AssetRelation.source_asset_id == UUID(source_id))
        )
    ).all()
    assert [(e.target_asset_id, e.relation_type) for e in rows] == [(target.id, "references")]


async def test_relative_in_bundle_links_are_ignored(client, session, fs_storage):
    author = await mk_user(session)
    # A slug that exists: a relative `v/<slug>` must still not resolve to it.
    lookalike = await mk_asset(session, author, title="Lookalike")
    await session.commit()
    await login_as(client, author)

    index = (
        "<html><body>"
        '<a href="page2.html">next</a>'
        f"<a href='v/{lookalike.slug}'>relative</a>"
        f'<a href="./v/{lookalike.slug}/doc.md">dot</a>'
        '<a href="#top">top</a>'
        "</body></html>"
    )
    source_id = await _upload_bundle(
        client, {"index.html": index, "page2.html": '<a href="index.html">back</a>'}
    )
    assert await _targets(session, source_id) == []


def test_link_hrefs_reads_quoted_and_bare_values():
    html = (
        '<A HREF="/v/abc">x</A><area shape=rect href=/v/def>'
        "<link rel=stylesheet href='style.css'><img src=\"/v/nope\">"
    )
    assert link_hrefs(html) == ["/v/abc", "/v/def", "style.css"]


def test_only_root_and_protocol_relative_links_are_made_absolute():
    html = '<a href="/v/abc">a</a><a href="//ics.example/v/def">b</a><a href="x.html">c</a>'
    assert _absolute_links(html, "https://ics.example/") == [
        "https://ics.example/v/abc",
        "https://ics.example/v/def",
    ]
