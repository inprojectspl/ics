"""End-to-end smoke for the projects + sharing flow.

A single deterministic test against the real API surface (routes called
directly with the same DB session a request handler would receive).

Golden path:
  1. User A creates a project.
  2. A invites user B by email (B has no account, so a stub user is created).
  3. B accepts the invite token.
  4. A uploads an asset and assigns it to the project.
  5. B (project editor) sees the file in the project listing.
  6. A shares a separate (out-of-project) asset with user C by email.
  7. C sees that asset in their "Shared with me" tab.
  8. A transfers ownership of the project to B.
  9. B (now project owner) deletes the project; A (now editor) can no longer get it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import tokens
from app.config import get_settings
from app.db import Base
from app.models import Asset, ProjectMember, User
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


async def _mk_user(session, *, email: str | None = None) -> User:
    u = User(
        email=email or f"u+{generate_slug(6)}@example.com",
        display_name="U",
        role="user",
        auth_method="password",
        email_verified_at=datetime.now(tz=UTC),
    )
    session.add(u)
    await session.flush()
    return u


async def _mk_asset(session, owner: User, title: str = "Doc") -> Asset:
    a = Asset(
        slug=generate_slug(),
        owner_id=owner.id,
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


@pytest.mark.asyncio
async def test_golden_path_projects_and_sharing(session):
    settings = get_settings()

    # 1. user A
    a = await _mk_user(session, email=f"alice+{generate_slug(4)}@example.com")
    await session.commit()

    # 1a. A creates a project
    project_dict = await proj_routes.create_project(
        proj_routes.CreateProjectIn(name="Q4 plan", description="draft"),
        a,
        session,
    )
    project_slug = project_dict["slug"]
    assert project_dict["my_role"] == "owner"

    # 2. A invites B by email (B has no account yet)
    b_email = f"bob+{generate_slug(4)}@example.com"
    invite_row = await proj_routes.invite_member(
        project_slug,
        proj_routes.InviteMemberIn(email=b_email, role="editor"),
        a,
        session,
        settings,
    )
    assert invite_row["role"] == "editor"
    assert invite_row["accepted_at"] is None

    b = (await session.execute(select(User).where(User.email == b_email))).scalar_one()
    assert b.auth_method == "invite"

    # 3. B accepts the invite via token
    member = (
        await session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project_dict["id"],
                ProjectMember.user_id == b.id,
            )
        )
    ).scalar_one()
    token = tokens.issue("project_invite", str(member.id))
    accept_res = await proj_routes.accept_invite(
        proj_routes.AcceptInviteIn(token=token),
        b,
        session,
    )
    assert accept_res["accepted"] is True
    assert accept_res["role"] == "editor"

    # Replay must fail.
    with pytest.raises(HTTPException) as ei:
        await proj_routes.accept_invite(
            proj_routes.AcceptInviteIn(token=token),
            b,
            session,
        )
    assert ei.value.status_code == 409

    # 4. A uploads an asset and assigns it to the project.
    project_asset = await _mk_asset(session, a, title="Project doc")
    await session.commit()
    assign_res = await assets_routes.patch_asset_project(
        project_asset.slug,
        assets_routes.PatchAssetProjectIn(project_id=project_dict["id"]),
        a,
        session,
    )
    assert assign_res["project_id"] == project_dict["id"]

    # 5. B (project editor) sees the asset in shared-with-me grouped under the project.
    swm = await shared_routes.shared_with_me(b, session)
    assert len(swm["projects"]) == 1
    block = swm["projects"][0]
    assert block["project"]["slug"] == project_slug
    assert block["project"]["my_role"] == "editor"
    titles = [x["title"] for x in block["assets"]]
    assert "Project doc" in titles

    # 6. A shares a separate (out-of-project) asset with user C by email.
    c_email = f"carol+{generate_slug(4)}@example.com"
    standalone_asset = await _mk_asset(session, a, title="Solo doc")
    await session.commit()
    share_res = await assets_routes.create_asset_share(
        standalone_asset.slug,
        assets_routes.CreateAssetShareIn(email=c_email, role="viewer"),
        a,
        session,
        settings,
    )
    assert share_res["role"] == "viewer"
    assert share_res["new_account"] is True
    c = (await session.execute(select(User).where(User.email == c_email))).scalar_one()

    # 7. C sees the standalone asset in shared-with-me.
    swm_c = await shared_routes.shared_with_me(c, session)
    assert swm_c["projects"] == []
    standalone = swm_c["standalone_assets"]
    assert len(standalone) == 1
    assert standalone[0]["title"] == "Solo doc"
    assert standalone[0]["my_role"] == "viewer"
    assert standalone[0]["owner"]["email"] == a.email

    # 8. A transfers ownership of the project to B (B was accepted earlier).
    transfer_res = await proj_routes.transfer_owner(
        project_slug,
        proj_routes.TransferOwnerIn(user_id=b.id),
        a,
        session,
    )
    assert transfer_res == {"transferred": True}

    # Confirm: B is now owner, A is editor.
    detail_b = await proj_routes.get_project(project_slug, b, session)
    roles = {m["user_id"]: m["role"] for m in detail_b["members"]}
    assert roles[str(b.id)] == "owner"
    assert roles[str(a.id)] == "editor"

    # 9. B deletes the project; A loses access.
    del_res = await proj_routes.delete_project(project_slug, b, session)
    assert del_res == {"deleted": True}
    with pytest.raises(HTTPException) as ei:
        await proj_routes.get_project(project_slug, a, session)
    assert ei.value.status_code == 404

    # The project-owned asset survives soft-delete of the project (ON DELETE SET NULL).
    asset_after = await session.get(Asset, project_asset.id)
    assert asset_after is not None
    assert asset_after.project_id is None
