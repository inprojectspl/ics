"""Per-user asset shares + shared-with-me listing.

Covers who can share, who can't, listing grouping, and the owner being
filtered out of their own results.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db import Base
from app.domain_errors import DomainError
from app.errors import domain_status
from app.models import Asset, AssetShare, Project, ProjectMember, User
from app.routes import assets as assets_routes
from app.routes import projects as proj_routes
from app.routes import shared as shared_routes
from app.slug import generate_slug


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(get_settings().database_url, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _mk_user(session, *, role: str = "user") -> User:
    u = User(
        email=f"u+{generate_slug(6)}@example.com",
        display_name="U",
        role=role,
        auth_method="password",
    )
    session.add(u)
    await session.flush()
    return u


async def _mk_asset(session, owner: User, *, project_id=None, title: str = "T") -> Asset:
    a = Asset(
        slug=generate_slug(),
        owner_id=owner.id,
        project_id=project_id,
        kind="md_single",
        title=title,
        storage_prefix="x",
        entry_path="x.md",
        security_status="clean",
        version=1,
    )
    session.add(a)
    await session.flush()
    return a


async def _mk_project_with_member(
    session,
    owner: User,
    member: User,
    *,
    role: str,
) -> Project:
    p_dict = await proj_routes.create_project(
        proj_routes.CreateProjectIn(name="P", description=None),
        owner,
        session,
    )
    project = await session.get(Project, p_dict["id"])
    pm = ProjectMember(
        project_id=project.id,
        user_id=member.id,
        role=role,
        accepted_at=datetime.now(tz=UTC),
    )
    session.add(pm)
    await session.commit()
    return project


# ---------- create share ----------


@pytest.mark.asyncio
async def test_owner_can_share_own_asset(session):
    owner = await _mk_user(session)
    bob = await _mk_user(session)
    await session.commit()
    asset = await _mk_asset(session, owner)
    await session.commit()
    settings = get_settings()
    row = await assets_routes.create_asset_share(
        asset.slug,
        assets_routes.CreateAssetShareIn(email=bob.email, role="editor"),
        owner,
        session,
        settings,
    )
    assert row["role"] == "editor"
    assert row["user_id"] == str(bob.id)


@pytest.mark.asyncio
async def test_create_share_for_new_email_creates_stub_user(session):
    owner = await _mk_user(session)
    await session.commit()
    asset = await _mk_asset(session, owner)
    await session.commit()
    settings = get_settings()
    new_email = f"new+{generate_slug(6)}@example.com"
    row = await assets_routes.create_asset_share(
        asset.slug,
        assets_routes.CreateAssetShareIn(email=new_email, role="viewer"),
        owner,
        session,
        settings,
    )
    assert row["new_account"] is True
    stub = (await session.execute(select(User).where(User.email == new_email))).scalar_one()
    assert stub.auth_method == "invite"


@pytest.mark.asyncio
async def test_share_to_owner_self_400(session):
    owner = await _mk_user(session)
    await session.commit()
    asset = await _mk_asset(session, owner)
    await session.commit()
    settings = get_settings()
    with pytest.raises(HTTPException) as ei:
        await assets_routes.create_asset_share(
            asset.slug,
            assets_routes.CreateAssetShareIn(email=owner.email, role="viewer"),
            owner,
            session,
            settings,
        )
    assert ei.value.status_code == 400


@pytest.mark.asyncio
async def test_duplicate_share_returns_409(session):
    owner = await _mk_user(session)
    bob = await _mk_user(session)
    await session.commit()
    asset = await _mk_asset(session, owner)
    await session.commit()
    settings = get_settings()
    await assets_routes.create_asset_share(
        asset.slug,
        assets_routes.CreateAssetShareIn(email=bob.email, role="viewer"),
        owner,
        session,
        settings,
    )
    with pytest.raises(HTTPException) as ei:
        await assets_routes.create_asset_share(
            asset.slug,
            assets_routes.CreateAssetShareIn(email=bob.email, role="editor"),
            owner,
            session,
            settings,
        )
    assert ei.value.status_code == 409


@pytest.mark.asyncio
async def test_project_owner_can_share_other_users_file_in_project(session):
    creator = await _mk_user(session)
    file_owner = await _mk_user(session)
    target = await _mk_user(session)
    await session.commit()
    project = await _mk_project_with_member(session, creator, file_owner, role="editor")
    asset = await _mk_asset(session, file_owner, project_id=project.id)
    await session.commit()
    settings = get_settings()
    # creator is the project owner; should be allowed to share file_owner's file.
    row = await assets_routes.create_asset_share(
        asset.slug,
        assets_routes.CreateAssetShareIn(email=target.email, role="viewer"),
        creator,
        session,
        settings,
    )
    assert row["role"] == "viewer"


@pytest.mark.asyncio
async def test_project_editor_cannot_share_others_file(session):
    creator = await _mk_user(session)
    file_owner = await _mk_user(session)
    editor = await _mk_user(session)
    target = await _mk_user(session)
    await session.commit()
    project = await _mk_project_with_member(session, creator, file_owner, role="editor")
    pm = ProjectMember(
        project_id=project.id,
        user_id=editor.id,
        role="editor",
        accepted_at=datetime.now(tz=UTC),
    )
    session.add(pm)
    await session.commit()
    asset = await _mk_asset(session, file_owner, project_id=project.id)
    await session.commit()
    settings = get_settings()
    with pytest.raises(HTTPException) as ei:
        await assets_routes.create_asset_share(
            asset.slug,
            assets_routes.CreateAssetShareIn(email=target.email, role="viewer"),
            editor,
            session,
            settings,
        )
    # 404 by convention: the editor can read the file (it's in their project),
    # but the share endpoint is owner-only and hides itself.
    assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_editor_can_share_own_file_even_in_project(session):
    creator = await _mk_user(session)
    editor = await _mk_user(session)
    target = await _mk_user(session)
    await session.commit()
    project = await _mk_project_with_member(session, creator, editor, role="editor")
    # editor is the owner of this asset; they can share their own file.
    asset = await _mk_asset(session, editor, project_id=project.id)
    await session.commit()
    settings = get_settings()
    row = await assets_routes.create_asset_share(
        asset.slug,
        assets_routes.CreateAssetShareIn(email=target.email, role="editor"),
        editor,
        session,
        settings,
    )
    assert row["role"] == "editor"


# ---------- list / delete share ----------


@pytest.mark.asyncio
async def test_list_and_delete_share(session):
    owner = await _mk_user(session)
    bob = await _mk_user(session)
    await session.commit()
    asset = await _mk_asset(session, owner)
    await session.commit()
    settings = get_settings()
    await assets_routes.create_asset_share(
        asset.slug,
        assets_routes.CreateAssetShareIn(email=bob.email, role="viewer"),
        owner,
        session,
        settings,
    )
    rows = await assets_routes.list_asset_shares(asset.slug, owner, session)
    assert len(rows) == 1
    assert rows[0]["email"] == bob.email

    await assets_routes.delete_asset_share(asset.slug, bob.id, owner, session)
    rows = await assets_routes.list_asset_shares(asset.slug, owner, session)
    assert rows == []


# ---------- patch project on asset ----------


@pytest.mark.asyncio
async def test_patch_asset_project_requires_editor_in_target(session):
    owner = await _mk_user(session)
    stranger = await _mk_user(session)
    await session.commit()
    asset = await _mk_asset(session, owner)
    # project owned by stranger; `owner` is not a member.
    p_dict = await proj_routes.create_project(
        proj_routes.CreateProjectIn(name="X", description=None),
        stranger,
        session,
    )
    target_project = await session.get(Project, p_dict["id"])
    await session.commit()
    with pytest.raises(DomainError) as ei:
        await assets_routes.patch_asset_project(
            asset.slug,
            assets_routes.PatchAssetProjectIn(project_id=target_project.id),
            owner,
            session,
        )
    assert domain_status(ei.value) == 403


@pytest.mark.asyncio
async def test_patch_asset_project_assigns_when_member(session):
    owner = await _mk_user(session)
    await session.commit()
    asset = await _mk_asset(session, owner)
    p_dict = await proj_routes.create_project(
        proj_routes.CreateProjectIn(name="P", description=None),
        owner,
        session,
    )
    out = await assets_routes.patch_asset_project(
        asset.slug,
        assets_routes.PatchAssetProjectIn(project_id=p_dict["id"]),
        owner,
        session,
    )
    assert out["project_id"] == p_dict["id"]


@pytest.mark.asyncio
async def test_patch_asset_project_unassign(session):
    owner = await _mk_user(session)
    await session.commit()
    p_dict = await proj_routes.create_project(
        proj_routes.CreateProjectIn(name="P", description=None),
        owner,
        session,
    )
    project = await session.get(Project, p_dict["id"])
    asset = await _mk_asset(session, owner, project_id=project.id)
    await session.commit()
    out = await assets_routes.patch_asset_project(
        asset.slug,
        assets_routes.PatchAssetProjectIn(project_id=None),
        owner,
        session,
    )
    assert out["project_id"] is None


# ---------- shared-with-me listing ----------


@pytest.mark.asyncio
async def test_shared_with_me_excludes_own_files(session):
    owner = await _mk_user(session)
    await session.commit()
    await _mk_asset(session, owner)
    await session.commit()
    out = await shared_routes.shared_with_me(owner, session)
    assert out["projects"] == []
    assert out["standalone_assets"] == []
    assert out["total"] == 0


@pytest.mark.asyncio
async def test_shared_with_me_groups_by_project(session):
    owner = await _mk_user(session)
    member = await _mk_user(session)
    await session.commit()
    project = await _mk_project_with_member(session, owner, member, role="viewer")
    _asset = await _mk_asset(session, owner, project_id=project.id, title="In project")
    await session.commit()
    out = await shared_routes.shared_with_me(member, session)
    assert len(out["projects"]) == 1
    block = out["projects"][0]
    assert block["project"]["id"] == str(project.id)
    assert block["project"]["my_role"] == "viewer"
    assert len(block["assets"]) == 1
    item = block["assets"][0]
    assert item["title"] == "In project"
    assert item["my_role"] == "viewer"
    assert item["owner"]["email"] == owner.email


@pytest.mark.asyncio
async def test_shared_with_me_standalone_asset_share(session):
    owner = await _mk_user(session)
    bob = await _mk_user(session)
    await session.commit()
    asset = await _mk_asset(session, owner, title="Solo")
    share = AssetShare(asset_id=asset.id, user_id=bob.id, role="editor")
    session.add(share)
    await session.commit()
    out = await shared_routes.shared_with_me(bob, session)
    assert out["projects"] == []
    assert len(out["standalone_assets"]) == 1
    item = out["standalone_assets"][0]
    assert item["my_role"] == "editor"
    assert item["owner"]["email"] == owner.email


@pytest.mark.asyncio
async def test_shared_with_me_strongest_role_wins(session):
    """Both project-viewer + asset-share-editor -> my_role='editor'."""
    owner = await _mk_user(session)
    member = await _mk_user(session)
    await session.commit()
    project = await _mk_project_with_member(session, owner, member, role="viewer")
    asset = await _mk_asset(session, owner, project_id=project.id)
    share = AssetShare(asset_id=asset.id, user_id=member.id, role="editor")
    session.add(share)
    await session.commit()
    out = await shared_routes.shared_with_me(member, session)
    block = out["projects"][0]
    item = block["assets"][0]
    assert item["my_role"] == "editor"
