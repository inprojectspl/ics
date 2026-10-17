"""A single Markdown upload stores the file under its base name: a client-sent
name with directory segments must not write into another document's folder,
neither on the first upload nor on a new version."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import Asset, AssetVersion
from tests.conftest import login_as, mk_user


async def _upload(client, name: str, content: bytes):
    return await client.post("/api/assets", files={"file": (name, content, "text/markdown")})


async def _victim(client, session, storage: Path):
    victim = await mk_user(session)
    await session.commit()
    await login_as(client, victim)
    r = await _upload(client, "plan.md", b"# Victim plan")
    assert r.status_code == 201, r.text
    slug = r.json()["slug"]
    target = storage / "assets" / slug / "v1" / "plan.md"
    assert target.read_bytes() == b"# Victim plan"
    return slug, target


async def _entry_path(session, slug: str) -> str:
    asset = (await session.execute(select(Asset).where(Asset.slug == slug))).scalar_one()
    return asset.entry_path


async def _version_count(session, slug: str) -> int:
    asset = (await session.execute(select(Asset).where(Asset.slug == slug))).scalar_one()
    rows = await session.scalars(select(AssetVersion).where(AssetVersion.asset_id == asset.id))
    return len(rows.all())


@pytest.mark.asyncio
async def test_upload_name_with_parent_segments_stays_in_its_own_document(
    client, session, fs_storage
):
    storage = Path(fs_storage)
    slug, target = await _victim(client, session, storage)
    versions_before = await _version_count(session, slug)

    attacker = await mk_user(session)
    await session.commit()
    await login_as(client, attacker)
    r = await _upload(client, f"../../{slug}/v1/plan.md", b"# Overwritten")

    assert r.status_code == 201, r.text
    assert target.read_bytes() == b"# Victim plan"
    assert await _version_count(session, slug) == versions_before
    own = r.json()
    assert await _entry_path(session, own["slug"]) == "plan.md"
    assert (storage / "assets" / own["slug"] / "v1" / "plan.md").read_bytes() == b"# Overwritten"


@pytest.mark.asyncio
async def test_new_version_name_with_parent_segments_stays_in_its_own_document(
    client, session, fs_storage
):
    storage = Path(fs_storage)
    slug, target = await _victim(client, session, storage)

    attacker = await mk_user(session)
    await session.commit()
    await login_as(client, attacker)
    r = await _upload(client, "mine.md", b"# Mine")
    assert r.status_code == 201, r.text
    own = r.json()

    r = await client.post(
        f"/api/assets/{own['id']}/versions",
        files={"files": (f"../../{slug}/v1/plan.md", b"# Overwritten", "text/markdown")},
    )

    assert r.status_code == 201, r.text
    assert target.read_bytes() == b"# Victim plan"
    assert await _version_count(session, slug) == 1
    assert (storage / "assets" / own["slug"] / "v2" / "plan.md").read_bytes() == b"# Overwritten"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "stored"), [("../.md", ".md"), ("..\\..\\x.md", "x.md"), ("/abs/x.md", "x.md")]
)
async def test_upload_name_is_reduced_to_its_base_name(client, session, fs_storage, name, stored):
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)
    r = await _upload(client, name, b"# x")
    assert r.status_code == 201, r.text
    assert await _entry_path(session, r.json()["slug"]) == stored
