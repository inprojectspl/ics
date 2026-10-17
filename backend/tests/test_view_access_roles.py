"""Read-only collaborators (project Observer, viewer share) can open files:
the read endpoints in `routes/assets/view.py` are viewer-level
(`get_viewable_asset_by_slug`), with a visitor gate on critical html_bundle
for the `viewer` role.

Matrix: project-viewer / share-viewer / pending-member / stranger x
doc / source / render / download / tree / static / html-grant.
"""

from __future__ import annotations

import pytest

from app.models import AssetShare, Project, ProjectMember, ShareLink
from app.slug import generate_slug, generate_token
from app.util import now as utc_now
from tests.conftest import login_as as _login
from tests.conftest import mk_asset, mk_user, put_blob

MD = b"# Title\n\nTest document body.\n"


async def _mk_md_single(session, owner):
    asset = await mk_asset(session, owner, kind="md_single", entry_path="doc.md")
    await put_blob(asset, "doc.md", MD)
    return asset


async def _grant_share(session, asset, user, *, role="viewer"):
    session.add(AssetShare(asset_id=asset.id, user_id=user.id, role=role))
    await session.flush()


async def _add_to_project(session, asset, member, *, role="viewer", accepted=True):
    """Asset attached to a project + `member` membership (Observer = viewer)."""
    project = Project(name="P", slug=generate_slug(), created_by=asset.owner_id)
    session.add(project)
    await session.flush()
    asset.project_id = project.id
    session.add(
        ProjectMember(
            project_id=project.id,
            user_id=member.id,
            role=role,
            accepted_at=utc_now() if accepted else None,
        )
    )
    await session.flush()


@pytest.mark.asyncio
async def test_project_viewer_can_open_doc(client, session, fs_storage):
    owner = await mk_user(session)
    observer = await mk_user(session)
    asset = await _mk_md_single(session, owner)
    await _add_to_project(session, asset, observer, role="viewer")
    await session.commit()
    await _login(client, observer)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/doc")
    assert r.status_code == 200
    body = r.json()
    assert body["slug"] == asset.slug
    assert body["html"]  # content was actually rendered
    # Role in the payload: the frontend hides edit actions for a viewer.
    assert body["my_role"] == "viewer"


@pytest.mark.asyncio
async def test_project_viewer_can_read_source_render_download(client, session, fs_storage):
    owner = await mk_user(session)
    observer = await mk_user(session)
    asset = await _mk_md_single(session, owner)
    await _add_to_project(session, asset, observer, role="viewer")
    await session.commit()
    await _login(client, observer)

    r_source = await client.get(f"/api/assets/by-slug/{asset.slug}/source")
    assert r_source.status_code == 200
    assert "Test document body" in r_source.json()["content"]

    r_render = await client.get(f"/api/assets/by-slug/{asset.slug}/render")
    assert r_render.status_code == 200

    r_dl = await client.get(f"/api/assets/by-slug/{asset.slug}/download")
    assert r_dl.status_code == 200


@pytest.mark.asyncio
async def test_project_viewer_can_open_collection_tree_and_file(client, session, fs_storage):
    owner = await mk_user(session)
    observer = await mk_user(session)
    asset = await mk_asset(session, owner, kind="md_collection", entry_path="index.md")
    await put_blob(asset, "index.md", b"# Index\n[[notes/a]]\n")
    await put_blob(asset, "notes/a.md", b"# A\n")
    await _add_to_project(session, asset, observer, role="viewer")
    await session.commit()
    await _login(client, observer)

    r_tree = await client.get(f"/api/assets/by-slug/{asset.slug}/tree")
    assert r_tree.status_code == 200
    assert "index.md" in r_tree.json()["paths"]

    r_file = await client.get(
        f"/api/assets/by-slug/{asset.slug}/file", params={"path": "notes/a.md"}
    )
    assert r_file.status_code == 200

    r_graph = await client.get(f"/api/assets/by-slug/{asset.slug}/graph")
    assert r_graph.status_code == 200


@pytest.mark.asyncio
async def test_pending_project_member_still_404(client, session, fs_storage):
    """An invitation that was not accepted grants no access (accepted_at IS NULL)."""
    owner = await mk_user(session)
    invited = await mk_user(session)
    asset = await _mk_md_single(session, owner)
    await _add_to_project(session, asset, invited, role="viewer", accepted=False)
    await session.commit()
    await _login(client, invited)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/doc")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_share_viewer_can_open_doc(client, session, fs_storage):
    owner = await mk_user(session)
    other = await mk_user(session)
    asset = await _mk_md_single(session, owner)
    await _grant_share(session, asset, other, role="viewer")
    await session.commit()
    await _login(client, other)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/doc")
    assert r.status_code == 200
    assert r.json()["my_role"] == "viewer"


@pytest.mark.asyncio
async def test_stranger_still_404_on_all_read_endpoints(client, session, fs_storage):
    owner = await mk_user(session)
    stranger = await mk_user(session)
    asset = await _mk_md_single(session, owner)
    await session.commit()
    await _login(client, stranger)

    for path in ("doc", "source", "render", "download", "tree", "graph", "html-grant"):
        r = await client.get(f"/api/assets/by-slug/{asset.slug}/{path}")
        assert r.status_code == 404, f"endpoint {path} reveals that the asset exists"


@pytest.mark.asyncio
async def test_owner_doc_reports_owner_role(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await _mk_md_single(session, owner)
    await session.commit()
    await _login(client, owner)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/doc")
    assert r.status_code == 200
    assert r.json()["my_role"] == "owner_file"


async def _mk_bundle(session, owner, *, security_status="clean"):
    asset = await mk_asset(
        session,
        owner,
        kind="html_bundle",
        entry_path="index.html",
        security_status=security_status,
    )
    await put_blob(asset, "index.html", b"<!doctype html><title>x</title>ok")
    return asset


@pytest.mark.asyncio
async def test_share_viewer_can_get_html_grant_and_static_for_clean_bundle(
    client, session, fs_storage
):
    owner = await mk_user(session)
    other = await mk_user(session)
    asset = await _mk_bundle(session, owner)
    await _grant_share(session, asset, other, role="viewer")
    await session.commit()
    await _login(client, other)

    r_grant = await client.get(f"/api/assets/by-slug/{asset.slug}/html-grant")
    assert r_grant.status_code == 200
    assert "/_/grant?t=" in r_grant.json()["url"]

    r_static = await client.get(f"/api/assets/by-slug/{asset.slug}/static/index.html")
    assert r_static.status_code == 200


@pytest.mark.asyncio
async def test_viewer_blocked_on_critical_bundle_static(client, session, fs_storage):
    """Critical without a bypass: viewer = visitor -> 410. The owner still
    sees it (same-origin preview before review)."""
    owner = await mk_user(session)
    other = await mk_user(session)
    asset = await _mk_bundle(session, owner, security_status="critical")
    await _grant_share(session, asset, other, role="viewer")
    await session.commit()

    await _login(client, other)
    r_viewer = await client.get(f"/api/assets/by-slug/{asset.slug}/static/index.html")
    assert r_viewer.status_code == 410

    r_dl = await client.get(f"/api/assets/by-slug/{asset.slug}/download")
    assert r_dl.status_code == 410


@pytest.mark.asyncio
async def test_owner_still_previews_critical_bundle_static(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await _mk_bundle(session, owner, security_status="critical")
    await session.commit()
    await _login(client, owner)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/static/index.html")
    assert r.status_code == 200


_REPORT = {"findings": [{"path": "index.html", "rule": "inline-script", "snippet": "<script>…"}]}


@pytest.mark.asyncio
async def test_doc_hides_security_report_from_viewer(client, session, fs_storage):
    """Scanner finding details are a review tool (editor+), not content for
    the reader: a viewer gets None, the status stays visible."""
    owner = await mk_user(session)
    other = await mk_user(session)
    asset = await _mk_bundle(session, owner)
    asset.security_report = _REPORT
    await _grant_share(session, asset, other, role="viewer")
    await session.commit()
    await _login(client, other)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/doc")
    assert r.status_code == 200
    body = r.json()
    assert body["security_report"] is None
    assert body["security_status"] == "clean"


@pytest.mark.asyncio
async def test_doc_shows_security_report_to_owner_and_share_editor(client, session, fs_storage):
    owner = await mk_user(session)
    editor = await mk_user(session)
    asset = await _mk_bundle(session, owner)
    asset.security_report = _REPORT
    await _grant_share(session, asset, editor, role="editor")
    await session.commit()

    await _login(client, owner)
    r_owner = await client.get(f"/api/assets/by-slug/{asset.slug}/doc")
    assert r_owner.json()["security_report"] == _REPORT

    await _login(client, editor)
    r_editor = await client.get(f"/api/assets/by-slug/{asset.slug}/doc")
    assert r_editor.json()["security_report"] == _REPORT


@pytest.mark.asyncio
async def test_share_doc_hides_security_report_from_anonymous(client, session, fs_storage):
    """An anonymous visitor with a link gets no security_report in
    /api/share/{token}/doc."""
    owner = await mk_user(session)
    asset = await _mk_bundle(session, owner)
    asset.security_report = _REPORT
    share = ShareLink(asset_id=asset.id, token=generate_token(), mode="public")
    session.add(share)
    await session.commit()

    r = await client.get(f"/api/share/{share.token}/doc")
    assert r.status_code == 200
    assert r.json()["security_report"] is None


@pytest.mark.asyncio
async def test_mcp_security_endpoint_not_a_bypass_for_viewer(client, session, fs_storage):
    """MCP GET /by-slug/{slug}/security requires editor+, so a read-only
    collaborator cannot use it to bypass the report hiding in /doc (viewer ->
    404, anti-enumeration convention); an editor gets the report."""
    owner = await mk_user(session)
    viewer = await mk_user(session)
    editor = await mk_user(session)
    asset = await _mk_bundle(session, owner)
    asset.security_report = _REPORT
    await _grant_share(session, asset, viewer, role="viewer")
    await _grant_share(session, asset, editor, role="editor")
    await session.commit()

    await _login(client, viewer)
    r_viewer = await client.get(f"/api/assets/by-slug/{asset.slug}/security")
    assert r_viewer.status_code == 404

    await _login(client, editor)
    r_editor = await client.get(f"/api/assets/by-slug/{asset.slug}/security")
    assert r_editor.status_code == 200
    assert r_editor.json()["security_report"] == _REPORT
