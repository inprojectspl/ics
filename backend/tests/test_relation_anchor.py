"""A relation's `target_anchor` and `target_path` must exist in the target's
current version (`services/relation_anchor.py`)."""

from __future__ import annotations

import pytest

from tests.conftest import login_as, mk_asset, mk_user, put_blob

_SPEC = "# Spec\n\n## Endpoints\n\nGET /x\n\n## Résumé\n\n```\n# not a heading\n```\n"


async def _setup(client, session):
    owner = await mk_user(session)
    source = await mk_asset(session, owner, title="Design")
    spec = await mk_asset(session, owner, title="Spec", entry_path="spec.md")
    guide = await mk_asset(session, owner, kind="md_collection", entry_path="README.md")
    page = await mk_asset(session, owner, kind="html_bundle", entry_path="index.html")
    await session.commit()
    await put_blob(spec, "spec.md", _SPEC.encode())
    await put_blob(guide, "README.md", b"# Guide\n")
    await put_blob(guide, "api/auth.md", b"# Auth\n\n## Tokens\n")
    await put_blob(page, "index.html", b'<h2 id="summary">Summary</h2>')
    await login_as(client, owner)
    return source, spec, guide, page


async def _add(client, source, target, relation_type="derived_from", **extra):
    return await client.post(
        f"/api/assets/{source.id}/relations",
        json={"relation_type": relation_type, "target_id": str(target.id), **extra},
    )


@pytest.mark.asyncio
async def test_existing_anchor_is_accepted_and_normalised(client, session, fs_storage):
    source, spec, _, _ = await _setup(client, session)

    r = await _add(client, source, spec, target_anchor="endpoints")
    assert r.status_code == 201, r.text
    assert r.json()["target_anchor"] == "endpoints"
    # Heading text and a leading `#` resolve to the anchor itself.
    r = await _add(client, source, spec, "depends_on", target_anchor="#Résumé")
    assert r.status_code == 201, r.text
    assert r.json()["target_anchor"] == "résumé"


@pytest.mark.asyncio
async def test_missing_anchor_is_refused(client, session, fs_storage):
    source, spec, _, _ = await _setup(client, session)
    for anchor in ("no-such-section", "not-a-heading"):
        r = await _add(client, source, spec, target_anchor=anchor)
        assert r.status_code == 400
        assert r.json()["code"] == "relation_target_anchor_not_found"


@pytest.mark.asyncio
async def test_collection_path_and_anchor(client, session, fs_storage):
    source, _, guide, _ = await _setup(client, session)

    r = await _add(client, source, guide, target_path="api/auth.md", target_anchor="tokens")
    assert r.status_code == 201, r.text
    r = await _add(client, source, guide, target_path="api/missing.md")
    assert r.status_code == 400
    assert r.json()["code"] == "relation_target_path_not_found"
    # Without a path the anchor is looked up in the entry file.
    r = await _add(client, source, guide, "references", target_anchor="tokens")
    assert r.status_code == 400
    assert r.json()["code"] == "relation_target_anchor_not_found"


@pytest.mark.asyncio
async def test_single_file_path_and_html_ids(client, session, fs_storage):
    source, spec, _, page = await _setup(client, session)

    r = await _add(client, source, spec, target_path="other.md")
    assert r.json()["code"] == "relation_target_path_not_found"
    r = await _add(client, source, spec, target_path="spec.md", target_anchor="spec")
    assert r.status_code == 201, r.text
    r = await _add(client, source, page, target_anchor="summary")
    assert r.status_code == 201, r.text
    r = await _add(client, source, page, "references", target_anchor="missing")
    assert r.json()["code"] == "relation_target_anchor_not_found"


@pytest.mark.asyncio
async def test_refusal_lists_the_valid_choices(client, session, fs_storage):
    source, spec, guide, page = await _setup(client, session)

    body = (await _add(client, source, spec, target_anchor="missing")).json()
    assert body["code"] == "relation_target_anchor_not_found"
    assert body["anchors"] == ["spec", "endpoints", "résumé"]
    assert "anchors_total" not in body
    body = (await _add(client, source, page, target_anchor="missing")).json()
    assert body["anchors"] == ["summary"]
    body = (await _add(client, source, guide, target_path="api/missing.md")).json()
    assert body["code"] == "relation_target_path_not_found"
    assert body["paths"] == ["README.md", "api/auth.md"]
    body = (await _add(client, source, spec, target_path="other.md")).json()
    assert body["paths"] == ["spec.md"]


@pytest.mark.asyncio
async def test_long_anchor_list_is_capped(client, session, fs_storage):
    source, spec, _, _ = await _setup(client, session)
    many = "".join(f"## Section {i}\n\n" for i in range(45))
    await put_blob(spec, "spec.md", many.encode())

    body = (await _add(client, source, spec, target_anchor="missing")).json()
    assert len(body["anchors"]) == 30
    assert body["anchors"][0] == "section-0"
    assert body["anchors_total"] == 45
    assert set(body) == {"detail", "code", "anchors", "anchors_total"}
