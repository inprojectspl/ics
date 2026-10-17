"""A new version of a bundle or a collection keeps the entry file the caller
names (`entry_path`), even when ICS would pick another one by its rules
(`index.html`, `README.md`), and rejects an entry that is not among the
uploaded files before writing anything."""

from __future__ import annotations

import pytest

from tests.conftest import login_as, mk_user


def _multipart(files: dict[str, bytes], mime: str) -> list[tuple[str, tuple[str, bytes, str]]]:
    return [("files", (path, body, mime)) for path, body in files.items()]


async def _create(client, endpoint: str, files: dict[str, bytes], mime: str) -> dict:
    r = await client.post(endpoint, files=_multipart(files, mime), data={"paths": list(files)})
    assert r.status_code == 201, r.text
    return r.json()


async def _new_version(client, asset_id: str, files: dict[str, bytes], mime: str, entry: str):
    return await client.post(
        f"/api/assets/{asset_id}/versions",
        files=_multipart(files, mime),
        data={"paths": list(files), "entry_path": entry},
    )


@pytest.mark.asyncio
async def test_bundle_version_keeps_the_named_entry(client, session, fs_storage):
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)
    pages = {"index.html": b"<p>index</p>", "app.html": b"<p>app</p>"}
    created = await _create(client, "/api/assets/html", pages, "text/html")

    r = await _new_version(client, created["id"], pages, "text/html", "app.html")

    assert r.status_code == 201, r.text
    assert r.json()["entry_path"] == "app.html"
    doc = (await client.get(f"/api/assets/by-slug/{created['slug']}/doc")).json()
    assert doc["entry_path"] == "app.html"


@pytest.mark.asyncio
async def test_collection_version_keeps_the_named_entry(client, session, fs_storage):
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)
    notes = {"README.md": b"# Readme", "guide.md": b"# Guide"}
    created = await _create(client, "/api/assets/collection", notes, "text/markdown")

    r = await _new_version(client, created["id"], notes, "text/markdown", "guide.md")

    assert r.status_code == 201, r.text
    assert r.json()["entry_path"] == "guide.md"


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["missing.html", "style.css", "../index.html"])
async def test_entry_outside_the_upload_is_rejected(client, session, fs_storage, entry):
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)
    files = {"index.html": b"<p>index</p>", "style.css": b"p{}"}
    created = await _create(client, "/api/assets/html", files, "text/html")

    r = await _new_version(client, created["id"], files, "text/html", entry)

    assert r.status_code == 400, r.text
    assert r.json()["code"] in ("invalid_entry_path", "invalid_path")
    versions = (await client.get(f"/api/assets/{created['id']}/versions")).json()
    assert [v["version"] for v in versions] == [1]
