"""Version diff: one response shape (`files[]`) for all kinds.

Also covers content of files present in only one version, HTML bundles
(including binary files), author metadata of the compared versions, and the
`viewer` access threshold on the endpoint.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models import AssetVersion, Project, ProjectMember
from app.services.version_diff import DIFF_COUNT_MAX_BYTES
from app.slug import generate_slug
from tests.conftest import login_as as _login
from tests.conftest import mk_asset, mk_user, put_blob


async def _two_versions(session, owner, kind, v1: dict[str, bytes], v2: dict[str, bytes]):
    """Asset with two versions in storage + history rows for both."""
    entry = next(iter(v2))
    asset = await mk_asset(session, owner, kind=kind, entry_path=entry)
    for path, blob in v1.items():
        await put_blob(asset, path, blob)
    asset.version = 2
    session.add_all(
        [
            AssetVersion(
                asset_id=asset.id,
                version=1,
                storage_prefix=f"{asset.storage_prefix}/v1",
                size_bytes=sum(len(b) for b in v1.values()),
                created_by=owner.id,
                created_at=datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
            ),
            AssetVersion(
                asset_id=asset.id,
                version=2,
                storage_prefix=f"{asset.storage_prefix}/v2",
                size_bytes=sum(len(b) for b in v2.values()),
                created_by=owner.id,
                created_at=datetime(2026, 2, 1, 9, 0, tzinfo=UTC),
            ),
        ]
    )
    await session.commit()
    for path, blob in v2.items():
        await put_blob(asset, path, blob)
    return asset


def _by_path(payload: dict) -> dict[str, dict]:
    return {f["path"]: f for f in payload["files"]}


@pytest.mark.asyncio
async def test_md_single_reports_one_file(client, session, fs_storage):
    """One shape for all kinds: md_single is `files[]` with one entry, and the
    content comes from `?path=`. The summary does not carry it, so the same
    bytes are not read twice."""
    owner = await mk_user(session)
    asset = await _two_versions(
        session, owner, "md_single", {"doc.md": b"alfa\n"}, {"doc.md": b"beta\n"}
    )
    await _login(client, owner)

    r = await client.get(f"/api/assets/{asset.id}/versions/1/diff/2")
    assert r.status_code == 200
    body = r.json()
    assert [f["path"] for f in body["files"]] == ["doc.md"]
    assert body["files"][0]["change"] == "modified"
    assert "diff" not in body

    per_file = await client.get(f"/api/assets/{asset.id}/versions/1/diff/2?path=doc.md")
    assert "beta" in per_file.json()["diff"]


@pytest.mark.asyncio
async def test_rejects_same_version(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await _two_versions(session, owner, "md_single", {"doc.md": b"a\n"}, {"doc.md": b"b\n"})
    await _login(client, owner)

    r = await client.get(f"/api/assets/{asset.id}/versions/2/diff/2")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_rejects_version_out_of_range(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await _two_versions(session, owner, "md_single", {"doc.md": b"a\n"}, {"doc.md": b"b\n"})
    await _login(client, owner)

    assert (await client.get(f"/api/assets/{asset.id}/versions/1/diff/99")).status_code == 404
    assert (await client.get(f"/api/assets/{asset.id}/versions/9/diff/2")).status_code == 404


@pytest.mark.asyncio
async def test_collection_counts_added_and_removed_lines(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await _two_versions(
        session,
        owner,
        "md_collection",
        {"README.md": b"one\ntwo\n", "old.md": b"vanishes\n"},
        {"README.md": b"one\nTWO\nthree\n", "new.md": b"a\nb\nc\n"},
    )
    await _login(client, owner)

    files = _by_path((await client.get(f"/api/assets/{asset.id}/versions/1/diff/2")).json())
    assert (files["README.md"]["added_lines"], files["README.md"]["removed_lines"]) == (2, 1)
    # Added file: all of its content counts as added.
    assert files["new.md"]["change"] == "added"
    assert (files["new.md"]["added_lines"], files["new.md"]["removed_lines"]) == (3, 0)
    assert files["old.md"]["change"] == "removed"
    assert (files["old.md"]["added_lines"], files["old.md"]["removed_lines"]) == (0, 1)


@pytest.mark.asyncio
async def test_html_bundle_separates_text_from_binary(client, session, fs_storage):
    """Bundles are diffed too: text files get a diff, binary files an entry
    without content."""
    owner = await mk_user(session)
    asset = await _two_versions(
        session,
        owner,
        "html_bundle",
        {"index.html": b"<p>old</p>\n"},
        # 0x80 is not valid UTF-8, so the file is treated as binary.
        {"index.html": b"<p>new</p>\n", "img/logo.png": b"\x89PNG\x80\x00binary"},
    )
    await _login(client, owner)

    files = _by_path((await client.get(f"/api/assets/{asset.id}/versions/1/diff/2")).json())
    assert files["index.html"]["binary"] is False
    assert files["index.html"]["added_lines"] == 1
    png = files["img/logo.png"]
    assert (png["change"], png["binary"]) == ("added", True)
    assert png["added_lines"] is None  # no counters for bytes
    assert png["size_to"] == len(b"\x89PNG\x80\x00binary")


@pytest.mark.asyncio
async def test_added_file_content_is_readable(client, session, fs_storage):
    """An added file can be expanded and read on its own."""
    owner = await mk_user(session)
    asset = await _two_versions(
        session,
        owner,
        "md_collection",
        {"README.md": b"x\n"},
        {"README.md": b"x\n", "Notes/deploy.md": b"# Deploy\n\nmake dev\n"},
    )
    await _login(client, owner)

    r = await client.get(f"/api/assets/{asset.id}/versions/1/diff/2?path=Notes/deploy.md")
    assert r.status_code == 200
    body = r.json()
    assert body["change"] == "added"
    assert "+# Deploy" in body["diff"]
    assert "make dev" in body["diff"]


@pytest.mark.asyncio
async def test_removed_file_content_is_readable(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await _two_versions(
        session,
        owner,
        "md_collection",
        {"README.md": b"x\n", "gone.md": b"old knowledge\n"},
        {"README.md": b"x\n"},
    )
    await _login(client, owner)

    body = (await client.get(f"/api/assets/{asset.id}/versions/1/diff/2?path=gone.md")).json()
    assert body["change"] == "removed"
    assert "-old knowledge" in body["diff"]


@pytest.mark.asyncio
async def test_binary_file_diff_is_415_with_mime(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await _two_versions(
        session,
        owner,
        "html_bundle",
        {"index.html": b"<p>a</p>\n"},
        {"index.html": b"<p>a</p>\n", "logo.png": b"\x89PNG\x80"},
    )
    await _login(client, owner)

    r = await client.get(f"/api/assets/{asset.id}/versions/1/diff/2?path=logo.png")
    assert r.status_code == 415
    detail = r.json()["detail"]
    assert detail["code"] == "binary_file"
    assert detail["mime"] == "image/png"


@pytest.mark.asyncio
async def test_path_missing_in_both_versions_is_404(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await _two_versions(
        session, owner, "md_collection", {"README.md": b"a\n"}, {"README.md": b"b\n"}
    )
    await _login(client, owner)

    r = await client.get(f"/api/assets/{asset.id}/versions/1/diff/2?path=never.md")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_meta_names_authors_of_both_versions(client, session, fs_storage):
    owner = await mk_user(session, display_name="First Author")
    asset = await _two_versions(session, owner, "md_single", {"doc.md": b"a\n"}, {"doc.md": b"b\n"})
    editor = await mk_user(session, display_name="Second Author")
    row = (
        await session.execute(
            select(AssetVersion).where(AssetVersion.asset_id == asset.id, AssetVersion.version == 2)
        )
    ).scalar_one()
    row.created_by = editor.id
    await session.commit()
    await _login(client, owner)

    body = (await client.get(f"/api/assets/{asset.id}/versions/1/diff/2")).json()
    assert body["from_meta"]["author"] == "First Author"
    assert body["to_meta"]["author"] == "Second Author"
    assert body["from_meta"]["created_at"].startswith("2026-01-01")


@pytest.mark.asyncio
async def test_project_viewer_can_diff_without_seeing_emails(client, session, fs_storage):
    """Anyone with access to the asset sees the diff; the author's full e-mail
    stays reserved for editor+."""
    owner = await mk_user(session)
    observer = await mk_user(session)
    project = Project(slug=generate_slug(8), name="P", created_by=owner.id)
    session.add(project)
    await session.flush()
    asset = await _two_versions(session, owner, "md_single", {"doc.md": b"a\n"}, {"doc.md": b"b\n"})
    asset.project_id = project.id
    session.add(
        ProjectMember(
            project_id=project.id,
            user_id=observer.id,
            role="viewer",
            accepted_at=datetime.now(UTC),
        )
    )
    await session.commit()
    await _login(client, observer)

    r = await client.get(f"/api/assets/{asset.id}/versions/1/diff/2")
    assert r.status_code == 200
    assert r.json()["from_meta"]["author_email"] is None


@pytest.mark.asyncio
async def test_stranger_gets_404(client, session, fs_storage):
    owner = await mk_user(session)
    outsider = await mk_user(session)
    asset = await _two_versions(session, owner, "md_single", {"doc.md": b"a\n"}, {"doc.md": b"b\n"})
    await _login(client, outsider)

    r = await client.get(f"/api/assets/{asset.id}/versions/1/diff/2")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_huge_file_skips_line_counts(client, session, fs_storage):
    """A minified one-liner must not block the summary: counters are `None`,
    and expanding the file still works."""
    owner = await mk_user(session)
    big_old = b"x" * (DIFF_COUNT_MAX_BYTES + 10)
    asset = await _two_versions(
        session,
        owner,
        "html_bundle",
        {"bundle.js": big_old},
        {"bundle.js": big_old + b"y"},
    )
    await _login(client, owner)

    files = _by_path((await client.get(f"/api/assets/{asset.id}/versions/1/diff/2")).json())
    entry = files["bundle.js"]
    assert entry["change"] == "modified"
    assert entry["added_lines"] is None and entry["removed_lines"] is None
    assert entry["size_to"] == len(big_old) + 1


@pytest.mark.asyncio
async def test_trailing_newline_change_is_counted(client, session, fs_storage):
    """The counter agrees with the diff content: a change to only the
    trailing newline counts as one removed and one added line."""
    owner = await mk_user(session)
    asset = await _two_versions(
        session, owner, "md_single", {"doc.md": b"content\n"}, {"doc.md": b"content"}
    )
    await _login(client, owner)

    files = _by_path((await client.get(f"/api/assets/{asset.id}/versions/1/diff/2")).json())
    assert (files["doc.md"]["added_lines"], files["doc.md"]["removed_lines"]) == (1, 1)
