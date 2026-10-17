"""Projects API + invite flow.

Covers CRUD, invite flow (new + existing account), owner
guardrails (no kick/demote/leave), transfer-owner atomicity, token
expiry & replay, sys-admin bypass.
"""

from __future__ import annotations

from datetime import UTC
from urllib.parse import unquote

import pytest
import pytest_asyncio
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import permissions, tokens
from app.config import get_settings
from app.db import Base
from app.domain_errors import DomainError
from app.errors import ApiError, domain_status
from app.models import Asset, EmailOutbox, Project, ProjectMember, User
from app.routes import projects as proj
from app.slug import generate_slug


async def _mk_project_asset(session, owner: User, project: Project, **kw) -> Asset:
    asset = Asset(
        slug=generate_slug(),
        owner_id=owner.id,
        project_id=project.id,
        kind=kw.get("kind", "md_single"),
        title=kw.get("title", "Doc"),
        storage_prefix=generate_slug(8),
        entry_path="doc.md",
        security_status="clean",
        version=1,
    )
    session.add(asset)
    await session.flush()
    return asset


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(get_settings().database_url, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _mk_user(session, *, role: str = "user", email: str | None = None) -> User:
    u = User(
        email=email or f"u+{generate_slug(6)}@example.com",
        display_name="U",
        role=role,
        auth_method="password",
    )
    session.add(u)
    await session.flush()
    return u


async def _mk_project(session, owner: User, name: str = "P") -> Project:
    out = await proj.create_project(
        proj.CreateProjectIn(name=name, description=None),
        owner,
        session,
    )
    project = await session.get(Project, out["id"])
    assert project is not None
    return project


async def _mk_accepted_member(
    session,
    project: Project,
    owner: User,
    role: str,
) -> User:
    """Invite a fresh user into `project` and mark the invite accepted."""
    from datetime import datetime

    member = await _mk_user(session)
    await proj.invite_member(
        project.slug,
        proj.InviteMemberIn(email=member.email, role=role),
        owner,
        session,
        get_settings(),
    )
    m = (
        await session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == member.id,
            )
        )
    ).scalar_one()
    m.accepted_at = datetime.now(tz=UTC)
    await session.commit()
    return member


# ---------- create / list / get / patch / delete ----------


@pytest.mark.asyncio
async def test_create_project_inserts_owner_member(session):
    creator = await _mk_user(session)
    await session.commit()
    out = await proj.create_project(
        proj.CreateProjectIn(name="My project", description="description"),
        creator,
        session,
    )
    assert out["name"] == "My project"
    assert out["my_role"] == "owner"
    assert out["member_count"] == 1
    members = (
        (await session.execute(select(ProjectMember).where(ProjectMember.project_id == out["id"])))
        .scalars()
        .all()
    )
    assert len(members) == 1
    assert members[0].role == "owner"
    assert members[0].accepted_at is not None


@pytest.mark.asyncio
async def test_list_only_returns_my_projects_for_regular_user(session):
    a = await _mk_user(session)
    b = await _mk_user(session)
    await session.commit()
    await _mk_project(session, a, "A's project")
    await _mk_project(session, b, "B's project")

    a_list = await proj.list_projects(a, session, page=1, page_size=200)
    assert [p["name"] for p in a_list["items"]] == ["A's project"]
    assert a_list["total"] == 1


@pytest.mark.asyncio
async def test_list_returns_all_for_sys_admin(session):
    admin = await _mk_user(session, role="admin")
    b = await _mk_user(session)
    await session.commit()
    await _mk_project(session, b, "B's project")
    admin_list = await proj.list_projects(admin, session, page=1, page_size=200)
    names = {p["name"] for p in admin_list["items"]}
    assert "B's project" in names


@pytest.mark.asyncio
async def test_get_project_non_member_404(session):
    owner = await _mk_user(session)
    stranger = await _mk_user(session)
    await session.commit()
    project = await _mk_project(session, owner)
    with pytest.raises(HTTPException) as ei:
        await proj.get_project(project.slug, stranger, session)
    assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_get_project_returns_full_asset_summary(session):
    # Project file rows must carry the same AssetSummary shape as the home
    # list (my_role, share modes, security, owner, ...) so the frontend renders
    # them with the same row component.
    owner = await _mk_user(session)
    await session.commit()
    project = await _mk_project(session, owner)
    await _mk_project_asset(session, owner, project, title="In project")
    await session.commit()

    out = await proj.get_project(project.slug, owner, session)
    assert len(out["assets"]) == 1
    row = out["assets"][0]
    for key in (
        "my_role",
        "access_source",
        "active_share_modes",
        "security_status",
        "version",
        "pinned_at",
        "project_id",
        "owner",
    ):
        assert key in row, f"missing {key}"
    assert row["my_role"] == "owner"
    assert row["project_id"] == str(project.id)


@pytest.mark.asyncio
async def test_get_project_asset_role_reflects_viewer_membership(session):
    # A viewer member opening the project sees the owner's file as "viewer";
    # that gates the row's edit/delete widgets on the frontend.
    owner = await _mk_user(session)
    await session.commit()
    project = await _mk_project(session, owner)
    viewer = await _mk_accepted_member(session, project, owner, "viewer")
    await _mk_project_asset(session, owner, project)
    await session.commit()

    out = await proj.get_project(project.slug, viewer, session)
    assert out["assets"][0]["my_role"] == "viewer"


# ---------- assert_project_contributor (shared upload/move gate) ----------


@pytest.mark.asyncio
async def test_assert_project_contributor_allows_owner_and_editor(session):
    owner = await _mk_user(session)
    await session.commit()
    project = await _mk_project(session, owner)
    assert (
        await permissions.assert_project_contributor(session, owner, project.id)
    ).id == project.id
    editor = await _mk_accepted_member(session, project, owner, "editor")
    assert (
        await permissions.assert_project_contributor(session, editor, project.id)
    ).id == project.id


@pytest.mark.asyncio
async def test_assert_project_contributor_viewer_forbidden(session):
    owner = await _mk_user(session)
    await session.commit()
    project = await _mk_project(session, owner)
    viewer = await _mk_accepted_member(session, project, owner, "viewer")
    with pytest.raises(DomainError) as ei:
        await permissions.assert_project_contributor(session, viewer, project.id)
    assert domain_status(ei.value) == 403


@pytest.mark.asyncio
async def test_assert_project_contributor_non_member_forbidden(session):
    owner = await _mk_user(session)
    stranger = await _mk_user(session)
    await session.commit()
    project = await _mk_project(session, owner)
    with pytest.raises(DomainError) as ei:
        await permissions.assert_project_contributor(session, stranger, project.id)
    assert domain_status(ei.value) == 403


@pytest.mark.asyncio
async def test_assert_project_contributor_missing_project_404(session):
    from uuid import uuid4

    user = await _mk_user(session)
    await session.commit()
    with pytest.raises(DomainError) as ei:
        await permissions.assert_project_contributor(session, user, uuid4())
    assert domain_status(ei.value) == 404


@pytest.mark.asyncio
async def test_assert_project_contributor_admin_bypass(session):
    owner = await _mk_user(session)
    admin = await _mk_user(session, role="admin")
    await session.commit()
    project = await _mk_project(session, owner)
    assert (
        await permissions.assert_project_contributor(session, admin, project.id)
    ).id == project.id


@pytest.mark.asyncio
async def test_patch_project_owner_only(session):
    owner = await _mk_user(session)
    await session.commit()
    project = await _mk_project(session, owner)
    out = await proj.patch_project(
        project.slug,
        proj.PatchProjectIn(name="New name", description=None),
        owner,
        session,
    )
    assert out["name"] == "New name"


@pytest.mark.asyncio
async def test_patch_project_trims_and_updates_description(session):
    owner = await _mk_user(session)
    await session.commit()
    project = await _mk_project(session, owner, name="Old name")
    out = await proj.patch_project(
        project.slug,
        proj.PatchProjectIn(name="  Padded name  ", description="new description"),
        owner,
        session,
    )
    assert out["name"] == "Padded name"  # validator trims edges
    assert out["description"] == "new description"


@pytest.mark.asyncio
async def test_patch_project_blank_name_rejected(session):
    # Whitespace-only name must 422 at the DTO layer, never persist empty.
    with pytest.raises(ValidationError):
        proj.PatchProjectIn(name="   ", description=None)
    with pytest.raises(ValidationError):
        proj.CreateProjectIn(name="   ", description=None)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["editor", "viewer"])
async def test_patch_project_non_owner_member_forbidden(session, role):
    owner = await _mk_user(session)
    await session.commit()
    project = await _mk_project(session, owner)
    member = await _mk_accepted_member(session, project, owner, role)
    with pytest.raises(HTTPException) as ei:
        await proj.patch_project(
            project.slug,
            proj.PatchProjectIn(name="Hack", description=None),
            member,
            session,
        )
    assert ei.value.status_code == 403


@pytest.mark.asyncio
async def test_patch_project_non_member_404(session):
    owner = await _mk_user(session)
    stranger = await _mk_user(session)
    await session.commit()
    project = await _mk_project(session, owner)
    with pytest.raises(HTTPException) as ei:
        await proj.patch_project(
            project.slug,
            proj.PatchProjectIn(name="Hack", description=None),
            stranger,
            session,
        )
    assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_patch_project_sys_admin_bypass(session):
    owner = await _mk_user(session)
    admin = await _mk_user(session, role="admin")
    await session.commit()
    project = await _mk_project(session, owner)
    # Admin is not a ProjectMember but may still rename.
    out = await proj.patch_project(
        project.slug,
        proj.PatchProjectIn(name="Admin rename", description=None),
        admin,
        session,
    )
    assert out["name"] == "Admin rename"


@pytest.mark.asyncio
async def test_delete_project_owner_only(session):
    owner = await _mk_user(session)
    await session.commit()
    project = await _mk_project(session, owner)
    res = await proj.delete_project(project.slug, owner, session)
    assert res == {"deleted": True}
    # Now fetching returns 404.
    with pytest.raises(HTTPException):
        await proj.get_project(project.slug, owner, session)


# ---------- invite flow ----------


@pytest.mark.asyncio
async def test_invite_new_account_creates_stub_user(session):
    owner = await _mk_user(session)
    await session.commit()
    project = await _mk_project(session, owner)
    settings = get_settings()
    new_email = f"new+{generate_slug(6)}@example.com"

    row = await proj.invite_member(
        project.slug,
        proj.InviteMemberIn(email=new_email, role="editor"),
        owner,
        session,
        settings,
    )
    assert row["role"] == "editor"
    assert row["accepted_at"] is None

    user = (await session.execute(select(User).where(User.email == new_email))).scalar_one()
    assert user.auth_method == "invite"
    assert user.email_verified_at is None

    outbox = (
        (await session.execute(select(EmailOutbox).where(EmailOutbox.to_email == new_email)))
        .scalars()
        .all()
    )
    assert len(outbox) == 1
    assert outbox[0].purpose == "invite"


@pytest.mark.asyncio
async def test_invite_new_account_can_set_password_and_join(session):
    """The e-mail to a person without an account carries a setup link; after
    setting a password they can sign in, accept and open the project."""
    import re

    from app import passwords
    from app.routes.auth import invite as auth_invite
    from app.routes.auth._models import SetupFromTokenIn

    owner = await _mk_user(session)
    await session.commit()
    project = await _mk_project(session, owner)
    new_email = f"new+{generate_slug(6)}@example.com"
    await proj.invite_member(
        project.slug,
        proj.InviteMemberIn(email=new_email, role="editor"),
        owner,
        session,
        get_settings(),
    )
    mail = (
        await session.execute(select(EmailOutbox).where(EmailOutbox.to_email == new_email))
    ).scalar_one()
    setup_token = re.search(r"/setup\?token=([^&\s]+)", mail.body)
    next_param = re.search(r"/setup\?token=[^&\s]+&next=(\S+)", mail.body)
    assert next_param and unquote(next_param.group(1)).startswith(
        f"/projects/{project.slug}/accept?t="
    )
    accept_token = re.search(r"/accept\?t=(\S+)", mail.body)
    assert setup_token and accept_token

    await auth_invite.setup_from_token(
        SetupFromTokenIn(token=setup_token.group(1), password="correct horse battery"),
        session,
    )
    user = (await session.execute(select(User).where(User.email == new_email))).scalar_one()
    await session.refresh(user)
    assert user.email_verified_at is not None
    assert passwords.verify_password("correct horse battery", user.password_hash)
    assert user.auth_method == "password"

    out = await proj.accept_invite(proj.AcceptInviteIn(token=accept_token.group(1)), user, session)
    assert out["project_slug"] == project.slug
    got = await proj.get_project(project.slug, user, session)
    assert got["my_role"] == "editor"


@pytest.mark.asyncio
async def test_invite_existing_account_no_duplicate_user(session):
    owner = await _mk_user(session)
    invited = await _mk_user(session)
    await session.commit()
    project = await _mk_project(session, owner)
    settings = get_settings()

    await proj.invite_member(
        project.slug,
        proj.InviteMemberIn(email=invited.email, role="viewer"),
        owner,
        session,
        settings,
    )

    users = (await session.execute(select(User).where(User.email == invited.email))).scalars().all()
    assert len(users) == 1


@pytest.mark.asyncio
async def test_invite_twice_returns_409(session):
    owner = await _mk_user(session)
    invited = await _mk_user(session)
    await session.commit()
    project = await _mk_project(session, owner)
    settings = get_settings()

    await proj.invite_member(
        project.slug,
        proj.InviteMemberIn(email=invited.email, role="viewer"),
        owner,
        session,
        settings,
    )
    with pytest.raises(HTTPException) as ei:
        await proj.invite_member(
            project.slug,
            proj.InviteMemberIn(email=invited.email, role="editor"),
            owner,
            session,
            settings,
        )
    assert ei.value.status_code == 409


@pytest.mark.asyncio
async def test_only_owner_can_invite(session):
    owner = await _mk_user(session)
    editor = await _mk_user(session)
    target = await _mk_user(session)
    await session.commit()
    project = await _mk_project(session, owner)
    settings = get_settings()

    # editor accepts membership
    await proj.invite_member(
        project.slug,
        proj.InviteMemberIn(email=editor.email, role="editor"),
        owner,
        session,
        settings,
    )
    m = (
        await session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == editor.id,
            )
        )
    ).scalar_one()
    from datetime import datetime

    m.accepted_at = datetime.now(tz=UTC)
    await session.commit()

    with pytest.raises(HTTPException) as ei:
        await proj.invite_member(
            project.slug,
            proj.InviteMemberIn(email=target.email, role="viewer"),
            editor,
            session,
            settings,
        )
    assert ei.value.status_code == 403


# ---------- owner guardrails ----------


@pytest.mark.asyncio
async def test_cannot_change_owner_role_via_patch(session):
    owner = await _mk_user(session)
    await session.commit()
    project = await _mk_project(session, owner)
    with pytest.raises(HTTPException) as ei:
        await proj.patch_member(
            project.slug,
            owner.id,
            proj.PatchMemberIn(role="editor"),
            owner,
            session,
        )
    assert ei.value.status_code == 400


@pytest.mark.asyncio
async def test_cannot_kick_owner(session):
    owner = await _mk_user(session)
    await session.commit()
    project = await _mk_project(session, owner)
    with pytest.raises(HTTPException) as ei:
        await proj.kick_member(project.slug, owner.id, owner, session)
    assert ei.value.status_code == 400


@pytest.mark.asyncio
async def test_owner_self_leave_409(session):
    owner = await _mk_user(session)
    await session.commit()
    project = await _mk_project(session, owner)
    with pytest.raises(HTTPException) as ei:
        await proj.leave_project(project.slug, owner, session)
    assert ei.value.status_code == 409


@pytest.mark.asyncio
async def test_editor_self_leave_ok(session):
    owner = await _mk_user(session)
    editor = await _mk_user(session)
    await session.commit()
    project = await _mk_project(session, owner)
    settings = get_settings()
    await proj.invite_member(
        project.slug,
        proj.InviteMemberIn(email=editor.email, role="editor"),
        owner,
        session,
        settings,
    )
    m = (
        await session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == editor.id,
            )
        )
    ).scalar_one()
    from datetime import datetime

    m.accepted_at = datetime.now(tz=UTC)
    await session.commit()

    res = await proj.leave_project(project.slug, editor, session)
    assert res == {"left": True}


# ---------- transfer-owner ----------


@pytest.mark.asyncio
async def test_transfer_owner_atomic(session):
    owner = await _mk_user(session)
    editor = await _mk_user(session)
    await session.commit()
    project = await _mk_project(session, owner)
    settings = get_settings()
    await proj.invite_member(
        project.slug,
        proj.InviteMemberIn(email=editor.email, role="editor"),
        owner,
        session,
        settings,
    )
    m = (
        await session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == editor.id,
            )
        )
    ).scalar_one()
    from datetime import datetime

    m.accepted_at = datetime.now(tz=UTC)
    await session.commit()

    await proj.transfer_owner(
        project.slug,
        proj.TransferOwnerIn(user_id=editor.id),
        owner,
        session,
    )
    owners = (
        (
            await session.execute(
                select(ProjectMember).where(
                    ProjectMember.project_id == project.id,
                    ProjectMember.role == "owner",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(owners) == 1
    assert owners[0].user_id == editor.id

    # Old owner is now editor.
    old = (
        await session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == owner.id,
            )
        )
    ).scalar_one()
    assert old.role == "editor"


@pytest.mark.asyncio
async def test_transfer_owner_requires_caller_to_be_owner(session):
    owner = await _mk_user(session)
    editor = await _mk_user(session)
    await session.commit()
    project = await _mk_project(session, owner)
    settings = get_settings()
    await proj.invite_member(
        project.slug,
        proj.InviteMemberIn(email=editor.email, role="editor"),
        owner,
        session,
        settings,
    )
    m = (
        await session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == editor.id,
            )
        )
    ).scalar_one()
    from datetime import datetime

    m.accepted_at = datetime.now(tz=UTC)
    await session.commit()

    with pytest.raises(HTTPException) as ei:
        await proj.transfer_owner(
            project.slug,
            proj.TransferOwnerIn(user_id=owner.id),
            editor,
            session,
        )
    assert ei.value.status_code == 403


@pytest.mark.asyncio
async def test_transfer_owner_target_must_be_accepted_member(session):
    owner = await _mk_user(session)
    stranger = await _mk_user(session)
    await session.commit()
    project = await _mk_project(session, owner)
    with pytest.raises(HTTPException) as ei:
        await proj.transfer_owner(
            project.slug,
            proj.TransferOwnerIn(user_id=stranger.id),
            owner,
            session,
        )
    assert ei.value.status_code == 400


@pytest.mark.asyncio
async def test_concurrent_transfer_owner_gets_409(session, monkeypatch):
    """Two transfers race: the loser trips the one-owner index and gets a 409,
    not a 500. The winner commits from a second connection after the loser
    has read the current owner and before it writes."""
    owner = await _mk_user(session)
    admin = await _mk_user(session, role="admin")
    await session.commit()
    project = await _mk_project(session, owner)
    loser_target = await _mk_accepted_member(session, project, owner, "editor")
    winner_target = await _mk_accepted_member(session, project, owner, "editor")

    project_id, winner_id = project.id, winner_target.id
    real_flush = session.flush
    raced = False

    async def flush_after_winner(*args, **kwargs):
        nonlocal raced
        if not raced:
            raced = True
            engine = create_async_engine(get_settings().database_url, future=True)
            try:
                async with async_sessionmaker(engine)() as other:
                    await proj.transfer_owner(
                        project.slug, proj.TransferOwnerIn(user_id=winner_target.id), owner, other
                    )
            finally:
                await engine.dispose()
        return await real_flush(*args, **kwargs)

    monkeypatch.setattr(session, "flush", flush_after_winner)
    with pytest.raises(ApiError) as ei:
        await proj.transfer_owner(
            project.slug, proj.TransferOwnerIn(user_id=loser_target.id), admin, session
        )
    assert ei.value.status_code == 409
    assert ei.value.code == "ownership_conflict"

    owners = (
        (
            await session.execute(
                select(ProjectMember.user_id).where(
                    ProjectMember.project_id == project_id, ProjectMember.role == "owner"
                )
            )
        )
        .scalars()
        .all()
    )
    assert owners == [winner_id]


# ---------- accept-invite token replay/expiry ----------


@pytest.mark.asyncio
async def test_accept_invite_marks_accepted(session):
    owner = await _mk_user(session)
    invited = await _mk_user(session)
    await session.commit()
    project = await _mk_project(session, owner)
    settings = get_settings()
    await proj.invite_member(
        project.slug,
        proj.InviteMemberIn(email=invited.email, role="viewer"),
        owner,
        session,
        settings,
    )
    member = (
        await session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == invited.id,
            )
        )
    ).scalar_one()
    token = tokens.issue("project_invite", str(member.id))

    out = await proj.accept_invite(
        proj.AcceptInviteIn(token=token),
        invited,
        session,
    )
    assert out["accepted"] is True
    assert out["project_slug"] == project.slug
    assert out["role"] == "viewer"


@pytest.mark.asyncio
async def test_accept_invite_replay_returns_409(session):
    owner = await _mk_user(session)
    invited = await _mk_user(session)
    await session.commit()
    project = await _mk_project(session, owner)
    settings = get_settings()
    await proj.invite_member(
        project.slug,
        proj.InviteMemberIn(email=invited.email, role="viewer"),
        owner,
        session,
        settings,
    )
    member = (
        await session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == invited.id,
            )
        )
    ).scalar_one()
    token = tokens.issue("project_invite", str(member.id))

    await proj.accept_invite(proj.AcceptInviteIn(token=token), invited, session)
    with pytest.raises(HTTPException) as ei:
        await proj.accept_invite(proj.AcceptInviteIn(token=token), invited, session)
    assert ei.value.status_code == 409


@pytest.mark.asyncio
async def test_accept_invite_wrong_user_forbidden(session):
    owner = await _mk_user(session)
    invited = await _mk_user(session)
    intruder = await _mk_user(session)
    await session.commit()
    project = await _mk_project(session, owner)
    settings = get_settings()
    await proj.invite_member(
        project.slug,
        proj.InviteMemberIn(email=invited.email, role="viewer"),
        owner,
        session,
        settings,
    )
    member = (
        await session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == invited.id,
            )
        )
    ).scalar_one()
    token = tokens.issue("project_invite", str(member.id))

    with pytest.raises(HTTPException) as ei:
        await proj.accept_invite(proj.AcceptInviteIn(token=token), intruder, session)
    assert ei.value.status_code == 403


@pytest.mark.asyncio
async def test_accept_invite_expired_token(session, monkeypatch):
    owner = await _mk_user(session)
    invited = await _mk_user(session)
    await session.commit()
    project = await _mk_project(session, owner)
    settings = get_settings()
    await proj.invite_member(
        project.slug,
        proj.InviteMemberIn(email=invited.email, role="viewer"),
        owner,
        session,
        settings,
    )
    member = (
        await session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == invited.id,
            )
        )
    ).scalar_one()
    token = tokens.issue("project_invite", str(member.id))

    def _raise_expired(purpose, t):
        raise tokens.TokenExpired("simulated expiry")

    monkeypatch.setattr(tokens, "verify", _raise_expired)
    with pytest.raises(HTTPException) as ei:
        await proj.accept_invite(proj.AcceptInviteIn(token=token), invited, session)
    assert ei.value.status_code == 410


# ---------- sys-admin bypass ----------


@pytest.mark.asyncio
async def test_sys_admin_can_invite_into_anothers_project(session):
    owner = await _mk_user(session)
    admin = await _mk_user(session, role="admin")
    target = await _mk_user(session)
    await session.commit()
    project = await _mk_project(session, owner)
    settings = get_settings()
    row = await proj.invite_member(
        project.slug,
        proj.InviteMemberIn(email=target.email, role="viewer"),
        admin,
        session,
        settings,
    )
    assert row["role"] == "viewer"


@pytest.mark.asyncio
async def test_sys_admin_can_delete_others_project(session):
    owner = await _mk_user(session)
    admin = await _mk_user(session, role="admin")
    await session.commit()
    project = await _mk_project(session, owner)
    res = await proj.delete_project(project.slug, admin, session)
    assert res == {"deleted": True}
