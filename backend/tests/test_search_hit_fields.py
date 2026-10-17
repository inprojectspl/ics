"""Search hits carry summary, doc type, freshness and, for a single Markdown
file, the snippet's path and line, so agents filter hits without extra calls."""

from __future__ import annotations

import secrets
import string

import pytest

from app.models import AssetRelation
from app.services.asset_projection import SUMMARY_PREVIEW_CHARS
from tests.conftest import login_as, mk_asset, mk_doc_type, mk_user


def _word() -> str:
    return "zq" + "".join(secrets.choice(string.ascii_lowercase) for _ in range(12))


@pytest.mark.asyncio
async def test_hits_have_summary_doc_type_freshness_and_line(client, session):
    owner = await mk_user(session)
    doc_type = await mk_doc_type(session)
    word = _word()
    old = await mk_asset(session, owner, title="Spec v1", entry_path="spec.md")
    old.search_content = f"# Spec\n\nIntro\n\nThe {word} section\n"
    old.summary = "x" * (SUMMARY_PREVIEW_CHARS + 50)
    old.doc_type = doc_type.key
    new = await mk_asset(session, owner, title=f"Spec v2 {word}", kind="md_collection")
    new.search_content = "no match in the text"
    session.add(
        AssetRelation(
            source_asset_id=new.id,
            target_asset_id=old.id,
            relation_type="supersedes",
            target_version=1,
            origin="manual",
            created_by=owner.id,
        )
    )
    await session.commit()
    await login_as(client, owner)

    r = await client.get("/api/assets/search-mcp", params={"q": word})
    assert r.status_code == 200, r.text
    hits = {h["slug"]: h for h in r.json()["items"]}

    hit_old = hits[old.slug]
    assert hit_old["freshness"] == "superseded"
    assert hit_old["doc_type"] == doc_type.key
    assert len(hit_old["summary"]) == SUMMARY_PREVIEW_CHARS
    assert hit_old["snippets"][0]["path"] == "spec.md"
    assert hit_old["snippets"][0]["line"] == 5

    hit_new = hits[new.slug]
    assert hit_new["freshness"] == "current"
    assert hit_new["summary"] is None
    # A match in the title only has no position in the text.
    assert all(s["line"] is None and s["path"] is None for s in hit_new["snippets"])
