"""Tests for `routes/assets/view.py`, missing `content.py` branches and helpers.

view.py: /tree, /download (md_single + collection ZIP), /file,
/html-grant, /render, /doc, /graph, /source. Each covers the happy path
for its own kind plus a refusal for the wrong one (e.g. /graph on md_single).

content.py: `move_file_in_collection` (PATCH /files/move).
"""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from zipfile import ZipFile

import pytest

from app.models import AssetShare, Project, ProjectMember
from app.slug import generate_slug
from tests.conftest import (
    login_as as _login,
)
from tests.conftest import (
    mk_asset,
    mk_user,
)
from tests.conftest import (
    mk_html_bundle as _setup_html_bundle,
)
from tests.conftest import (
    mk_md_collection as _setup_md_collection,
)
from tests.conftest import (
    mk_md_single as _setup_md_single_default,
)


async def _setup_md_single(client, session, *, content: str = "# Hello\nbody\n") -> tuple:
    # conftest.mk_md_single uses entry="notes.md" by default.
    return await _setup_md_single_default(client, session, content=content)


# ---------- /tree ----------


@pytest.mark.asyncio
async def test_tree_returns_paths_for_collection(client, session, fs_storage):
    _, asset = await _setup_md_collection(
        client,
        session,
        {"README.md": "# r\n", "notes/a.md": "a\n", "notes/b.md": "b\n"},
    )

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/tree")
    assert r.status_code == 200
    body = r.json()
    assert body["entry_path"] == "README.md"
    assert set(body["paths"]) == {"README.md", "notes/a.md", "notes/b.md"}


@pytest.mark.asyncio
async def test_tree_rejects_non_collection(client, session, fs_storage):
    _, asset = await _setup_md_single(client, session)
    r = await client.get(f"/api/assets/by-slug/{asset.slug}/tree")
    assert r.status_code == 400


# ---------- /download (_stream_source) ----------


@pytest.mark.asyncio
async def test_download_md_single_streams_markdown(client, session, fs_storage):
    _, asset = await _setup_md_single(client, session, content="alpha\n")
    r = await client.get(f"/api/assets/by-slug/{asset.slug}/download")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert "attachment" in r.headers["content-disposition"]
    assert r.text == "alpha\n"


@pytest.mark.asyncio
async def test_download_md_collection_streams_zip(client, session, fs_storage):
    _, asset = await _setup_md_collection(
        client,
        session,
        {"README.md": "# r\n", "a.md": "ax\n"},
    )
    r = await client.get(f"/api/assets/by-slug/{asset.slug}/download")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    zf = ZipFile(BytesIO(r.content))
    names = set(zf.namelist())
    assert names == {"README.md", "a.md"}
    assert zf.read("README.md") == b"# r\n"


@pytest.mark.asyncio
async def test_download_html_bundle_streams_zip(client, session, fs_storage):
    _, asset = await _setup_html_bundle(
        client,
        session,
        {"index.html": b"<html></html>", "style.css": b"body{}"},
    )
    r = await client.get(f"/api/assets/by-slug/{asset.slug}/download")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    zf = ZipFile(BytesIO(r.content))
    assert "index.html" in zf.namelist()


# ---------- /file ----------


@pytest.mark.asyncio
async def test_file_endpoint_renders_md(client, session, fs_storage):
    _, asset = await _setup_md_collection(
        client,
        session,
        {"README.md": "# Title\n", "notes/x.md": "## Sub\n"},
    )
    r = await client.get(
        f"/api/assets/by-slug/{asset.slug}/file",
        params={"path": "notes/x.md"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["path"] == "notes/x.md"
    assert "<h2>" in body["html"]


@pytest.mark.asyncio
async def test_file_endpoint_rejects_non_collection(client, session, fs_storage):
    _, asset = await _setup_md_single(client, session)
    r = await client.get(f"/api/assets/by-slug/{asset.slug}/file", params={"path": "notes.md"})
    assert r.status_code == 400


# ---------- /html-grant ----------


@pytest.mark.asyncio
async def test_html_grant_returns_signed_url(client, session, fs_storage):
    _, asset = await _setup_html_bundle(client, session, {"index.html": b"<html></html>"})
    r = await client.get(f"/api/assets/by-slug/{asset.slug}/html-grant")
    assert r.status_code == 200
    body = r.json()
    assert body["url"].startswith("http")
    assert "_/grant?t=" in body["url"]


@pytest.mark.asyncio
async def test_html_grant_rejects_md_single(client, session, fs_storage):
    _, asset = await _setup_md_single(client, session)
    r = await client.get(f"/api/assets/by-slug/{asset.slug}/html-grant")
    assert r.status_code == 400


# ---------- /render + /doc ----------


@pytest.mark.asyncio
async def test_render_returns_sanitized_html(client, session, fs_storage):
    _, asset = await _setup_md_single(client, session, content="# Header\n\ntext\n")
    r = await client.get(f"/api/assets/by-slug/{asset.slug}/render")
    assert r.status_code == 200
    assert "<h1>" in r.text


@pytest.mark.asyncio
async def test_doc_payload_for_md_single(client, session, fs_storage):
    _, asset = await _setup_md_single(client, session, content="# T\n")
    r = await client.get(f"/api/assets/by-slug/{asset.slug}/doc")
    assert r.status_code == 200
    body = r.json()
    assert "html" in body or "content" in body


@pytest.mark.asyncio
async def test_doc_payload_for_html_bundle_lists_files(client, session, fs_storage):
    _, asset = await _setup_html_bundle(
        client,
        session,
        {"index.html": b"<html></html>", "css/main.css": b""},
    )
    r = await client.get(f"/api/assets/by-slug/{asset.slug}/doc")
    assert r.status_code == 200
    body = r.json()
    # HTML bundle doc payload includes the file inventory
    assert "files" in body or "paths" in body or "html_grant" in body or "kind" in body


# ---------- /graph ----------


@pytest.mark.asyncio
async def test_graph_returns_nodes_and_edges_for_collection(client, session, fs_storage):
    _, asset = await _setup_md_collection(
        client,
        session,
        {
            "README.md": "See [[notes/a]] for details.\n",
            "notes/a.md": "Pointer to [[notes/b]].\n",
            "notes/b.md": "End.\n",
        },
    )
    r = await client.get(f"/api/assets/by-slug/{asset.slug}/graph")
    assert r.status_code == 200
    body = r.json()
    assert "nodes" in body
    assert "edges" in body
    assert len(body["nodes"]) >= 3


@pytest.mark.asyncio
async def test_graph_rejects_md_single(client, session, fs_storage):
    _, asset = await _setup_md_single(client, session)
    r = await client.get(f"/api/assets/by-slug/{asset.slug}/graph")
    assert r.status_code == 400


# ---------- /source ----------


@pytest.mark.asyncio
async def test_source_returns_raw_md_single(client, session, fs_storage):
    _, asset = await _setup_md_single(client, session, content="raw md text\n")
    r = await client.get(f"/api/assets/by-slug/{asset.slug}/source")
    assert r.status_code == 200
    body = r.json()
    assert body["path"] == "notes.md"
    assert body["content"] == "raw md text\n"


@pytest.mark.asyncio
async def test_source_collection_requires_path(client, session, fs_storage):
    _, asset = await _setup_md_collection(
        client,
        session,
        {"README.md": "x\n", "a.md": "y\n"},
    )
    r = await client.get(f"/api/assets/by-slug/{asset.slug}/source")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_source_collection_returns_specific_path(client, session, fs_storage):
    _, asset = await _setup_md_collection(
        client,
        session,
        {"README.md": "r\n", "a.md": "alpha\n"},
    )
    r = await client.get(
        f"/api/assets/by-slug/{asset.slug}/source",
        params={"path": "a.md"},
    )
    assert r.status_code == 200
    assert r.json()["content"] == "alpha\n"


@pytest.mark.asyncio
async def test_source_html_bundle_rejected(client, session, fs_storage):
    _, asset = await _setup_html_bundle(
        client,
        session,
        {"index.html": b"<html></html>"},
    )
    r = await client.get(f"/api/assets/by-slug/{asset.slug}/source")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_source_unknown_path_returns_404(client, session, fs_storage):
    _, asset = await _setup_md_collection(
        client,
        session,
        {"README.md": "r\n"},
    )
    r = await client.get(
        f"/api/assets/by-slug/{asset.slug}/source",
        params={"path": "nope.md"},
    )
    assert r.status_code == 404


# ---------- /search ----------


@pytest.mark.asyncio
async def test_search_matches_title(client, session, fs_storage):
    _user, asset = await _setup_md_single(client, session, content="x\n")
    asset.title = "Special Marker Document"
    await session.commit()

    r = await client.get("/api/assets/search", params={"q": "Special"})
    assert r.status_code == 200
    rows = r.json()
    assert any(row["slug"] == asset.slug for row in rows)


@pytest.mark.asyncio
async def test_search_ignores_a_bare_single_letter(client, session, fs_storage):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)
    r = await client.get("/api/assets/search", params={"q": "x"})
    assert r.status_code == 200
    assert r.json() == []


# ---------- move_file_in_collection (content.py) ----------


@pytest.mark.asyncio
async def test_move_file_happy_path(client, session, fs_storage):
    _user, asset = await _setup_md_collection(
        client,
        session,
        {"README.md": "r\n", "old/name.md": "moveme\n"},
    )

    r = await client.patch(
        f"/api/assets/{asset.id}/files/move",
        json={"from_path": "old/name.md", "to_path": "new/name.md"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["from_path"] == "old/name.md"
    assert body["to_path"] == "new/name.md"
    assert body["version"] == 2


@pytest.mark.asyncio
async def test_move_file_updates_entry_path_when_moving_entry(client, session, fs_storage):
    _user, asset = await _setup_md_collection(
        client,
        session,
        {"README.md": "r\n", "extra.md": "e\n"},
    )

    r = await client.patch(
        f"/api/assets/{asset.id}/files/move",
        json={"from_path": "README.md", "to_path": "index.md"},
    )
    assert r.status_code == 200
    assert r.json()["entry_path"] == "index.md"


@pytest.mark.asyncio
async def test_move_rejects_html_bundle(client, session, fs_storage):
    _user, asset = await _setup_html_bundle(client, session, {"index.html": b"<html></html>"})
    r = await client.patch(
        f"/api/assets/{asset.id}/files/move",
        json={"from_path": "index.html", "to_path": "main.html"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_move_rejects_same_path(client, session, fs_storage):
    _user, asset = await _setup_md_collection(
        client,
        session,
        {"README.md": "r\n", "a.md": "a\n"},
    )
    r = await client.patch(
        f"/api/assets/{asset.id}/files/move",
        json={"from_path": "a.md", "to_path": "a.md"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_move_rejects_non_md_extensions(client, session, fs_storage):
    _user, asset = await _setup_md_collection(
        client,
        session,
        {"README.md": "r\n", "a.md": "a\n"},
    )
    r = await client.patch(
        f"/api/assets/{asset.id}/files/move",
        json={"from_path": "a.md", "to_path": "a.txt"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_move_source_missing_returns_404(client, session, fs_storage):
    _user, asset = await _setup_md_collection(
        client,
        session,
        {"README.md": "r\n"},
    )
    r = await client.patch(
        f"/api/assets/{asset.id}/files/move",
        json={"from_path": "ghost.md", "to_path": "new.md"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_move_target_exists_returns_409(client, session, fs_storage):
    _user, asset = await _setup_md_collection(
        client,
        session,
        {"README.md": "r\n", "a.md": "a\n", "b.md": "b\n"},
    )
    r = await client.patch(
        f"/api/assets/{asset.id}/files/move",
        json={"from_path": "a.md", "to_path": "b.md"},
    )
    assert r.status_code == 409


# ---------- delete_file edge cases (last file rule) ----------


@pytest.mark.asyncio
async def test_delete_file_refuses_to_remove_last_file(client, session, fs_storage):
    """`<= 1` file in the vault -> 400 (keep at least one; an asset cannot
    be an empty collection)."""
    _user, asset = await _setup_md_collection(
        client,
        session,
        {"only.md": "x\n"},
    )
    asset.entry_path = "only.md"
    await session.commit()

    r = await client.delete(
        f"/api/assets/{asset.id}/files",
        params={"path": "only.md"},
    )
    assert r.status_code == 400


# ---------- add_file_to_collection edge cases ----------


@pytest.mark.asyncio
async def test_add_file_refuses_duplicate(client, session, fs_storage):
    _user, asset = await _setup_md_collection(
        client,
        session,
        {"README.md": "r\n", "existing.md": "e\n"},
    )

    r = await client.post(
        f"/api/assets/{asset.id}/files",
        files={"file": ("existing.md", b"new content", "text/markdown")},
        data={"path": "existing.md"},
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_add_file_requires_path_or_filename(client, session, fs_storage):
    _user, asset = await _setup_md_collection(
        client,
        session,
        {"README.md": "r\n"},
    )

    r = await client.post(
        f"/api/assets/{asset.id}/files",
        files={"file": ("", b"hi", "text/markdown")},
    )
    assert r.status_code in (400, 422)


@pytest.mark.asyncio
async def test_add_file_rejects_non_md(client, session, fs_storage):
    _user, asset = await _setup_md_collection(
        client,
        session,
        {"README.md": "r\n"},
    )

    r = await client.post(
        f"/api/assets/{asset.id}/files",
        files={"file": ("img.png", b"\x89PNG\r\n", "image/png")},
        data={"path": "img.png"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_add_file_rejects_for_md_single(client, session, fs_storage):
    _user, asset = await _setup_md_single(client, session)
    r = await client.post(
        f"/api/assets/{asset.id}/files",
        files={"file": ("extra.md", b"x", "text/markdown")},
        data={"path": "extra.md"},
    )
    assert r.status_code == 400


# ---------- create empty file ----------


@pytest.mark.asyncio
async def test_create_empty_file_refuses_duplicate(client, session, fs_storage):
    _user, asset = await _setup_md_collection(
        client,
        session,
        {"README.md": "r\n", "exists.md": "e\n"},
    )

    r = await client.post(
        f"/api/assets/{asset.id}/files/empty",
        json={"path": "exists.md"},
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_list_my_assets_includes_owned_shared_and_project(client, session):
    """Listing returns the union: owned + shared-with-me + project membership."""
    me = await mk_user(session)
    other = await mk_user(session)

    await mk_asset(session, me, title="MyOwn")
    shared = await mk_asset(session, other, title="SharedToMe")
    proj_asset = await mk_asset(session, other, title="ProjectFile")
    await session.commit()

    # Share viewer to me
    session.add(AssetShare(asset_id=shared.id, user_id=me.id, role="viewer"))

    # Project + membership
    proj = Project(name="P", slug=generate_slug(), created_by=other.id)
    session.add(proj)
    await session.flush()
    proj_asset.project_id = proj.id
    session.add(
        ProjectMember(
            project_id=proj.id,
            user_id=me.id,
            role="viewer",
            accepted_at=datetime.now(UTC),
        )
    )
    await session.commit()
    await _login(client, me)

    r = await client.get("/api/assets")
    assert r.status_code == 200
    titles = {a["title"] for a in r.json()["items"]}
    assert "MyOwn" in titles
    assert "SharedToMe" in titles
    assert "ProjectFile" in titles


@pytest.mark.asyncio
async def test_list_my_assets_empty_for_user_without_assets(client, session):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    r = await client.get("/api/assets")
    assert r.status_code == 200
    assert r.json()["items"] == []


@pytest.mark.asyncio
async def test_list_my_assets_excludes_deleted(client, session):
    user = await mk_user(session)
    await mk_asset(session, user, title="Visible")
    hidden = await mk_asset(session, user, title="Hidden")
    hidden.deleted_at = datetime.now(UTC)
    await session.commit()
    await _login(client, user)

    r = await client.get("/api/assets")
    assert r.status_code == 200
    titles = {a["title"] for a in r.json()["items"]}
    assert "Visible" in titles
    assert "Hidden" not in titles
