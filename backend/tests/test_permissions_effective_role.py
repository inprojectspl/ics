"""Matrix tests for `permissions.effective_role`.

Covers the lattice:
  None < viewer < editor < project_owner < owner_file

Combines ownership, ProjectMember, AssetShare, AssetProjectShare (ADR-0017)
and system-admin bypass.
"""

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db import Base
from app.models import Asset, AssetProjectShare, AssetShare, Project, ProjectMember, User
from app.permissions import effective_role
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


def _user(email_prefix: str = "u", *, role: str = "user") -> User:
    return User(
        email=f"{email_prefix}+{generate_slug(6)}@example.com",
        display_name=email_prefix,
        role=role,
    )


def _project(name: str = "P", *, created_by) -> Project:
    return Project(slug=generate_slug(8), name=name, created_by=created_by)


def _asset(owner_id, *, project_id=None) -> Asset:
    return Asset(
        slug=generate_slug(),
        owner_id=owner_id,
        project_id=project_id,
        kind="md_single",
        title="t",
        storage_prefix="x",
        entry_path="x.md",
        security_status="clean",
        version=1,
    )


def _now():
    return datetime.now(tz=UTC)


@pytest.mark.asyncio
async def test_owner_of_asset_is_owner_file(session):
    owner = _user("owner")
    session.add(owner)
    await session.flush()
    asset = _asset(owner.id)
    session.add(asset)
    await session.commit()
    assert await effective_role(session, owner, asset) == "owner_file"


@pytest.mark.asyncio
async def test_system_admin_is_owner_file_on_any_asset(session):
    owner = _user("owner")
    admin = _user("admin", role="admin")
    session.add_all([owner, admin])
    await session.flush()
    asset = _asset(owner.id)
    session.add(asset)
    await session.commit()
    assert await effective_role(session, admin, asset) == "owner_file"


@pytest.mark.asyncio
async def test_stranger_with_no_grants_is_none(session):
    owner = _user("o")
    stranger = _user("x")
    session.add_all([owner, stranger])
    await session.flush()
    asset = _asset(owner.id)
    session.add(asset)
    await session.commit()
    assert await effective_role(session, stranger, asset) is None


@pytest.mark.asyncio
async def test_project_member_owner_yields_project_owner(session):
    owner = _user("o")
    member = _user("m")
    session.add_all([owner, member])
    await session.flush()
    project = _project(created_by=owner.id)
    session.add(project)
    await session.flush()
    asset = _asset(owner.id, project_id=project.id)
    pm = ProjectMember(project_id=project.id, user_id=member.id, role="owner", accepted_at=_now())
    session.add_all([asset, pm])
    await session.commit()
    assert await effective_role(session, member, asset) == "project_owner"


@pytest.mark.asyncio
async def test_project_member_editor_yields_editor(session):
    owner = _user("o")
    member = _user("m")
    session.add_all([owner, member])
    await session.flush()
    project = _project(created_by=owner.id)
    session.add(project)
    await session.flush()
    asset = _asset(owner.id, project_id=project.id)
    pm = ProjectMember(project_id=project.id, user_id=member.id, role="editor", accepted_at=_now())
    session.add_all([asset, pm])
    await session.commit()
    assert await effective_role(session, member, asset) == "editor"


@pytest.mark.asyncio
async def test_project_member_viewer_yields_viewer(session):
    owner = _user("o")
    member = _user("m")
    session.add_all([owner, member])
    await session.flush()
    project = _project(created_by=owner.id)
    session.add(project)
    await session.flush()
    asset = _asset(owner.id, project_id=project.id)
    pm = ProjectMember(project_id=project.id, user_id=member.id, role="viewer", accepted_at=_now())
    session.add_all([asset, pm])
    await session.commit()
    assert await effective_role(session, member, asset) == "viewer"


@pytest.mark.asyncio
async def test_pending_invite_does_not_grant_access(session):
    owner = _user("o")
    member = _user("m")
    session.add_all([owner, member])
    await session.flush()
    project = _project(created_by=owner.id)
    session.add(project)
    await session.flush()
    asset = _asset(owner.id, project_id=project.id)
    pm = ProjectMember(project_id=project.id, user_id=member.id, role="editor", accepted_at=None)
    session.add_all([asset, pm])
    await session.commit()
    assert await effective_role(session, member, asset) is None


@pytest.mark.asyncio
async def test_asset_share_editor_yields_editor(session):
    owner = _user("o")
    bob = _user("b")
    session.add_all([owner, bob])
    await session.flush()
    asset = _asset(owner.id)
    session.add(asset)
    await session.flush()
    share = AssetShare(asset_id=asset.id, user_id=bob.id, role="editor")
    session.add(share)
    await session.commit()
    assert await effective_role(session, bob, asset) == "editor"


@pytest.mark.asyncio
async def test_asset_share_viewer_yields_viewer(session):
    owner = _user("o")
    bob = _user("b")
    session.add_all([owner, bob])
    await session.flush()
    asset = _asset(owner.id)
    session.add(asset)
    await session.flush()
    share = AssetShare(asset_id=asset.id, user_id=bob.id, role="viewer")
    session.add(share)
    await session.commit()
    assert await effective_role(session, bob, asset) == "viewer"


@pytest.mark.asyncio
async def test_project_viewer_plus_asset_editor_wins_editor(session):
    """Two paths to access: the strongest wins."""
    owner = _user("o")
    bob = _user("b")
    session.add_all([owner, bob])
    await session.flush()
    project = _project(created_by=owner.id)
    session.add(project)
    await session.flush()
    asset = _asset(owner.id, project_id=project.id)
    session.add(asset)
    await session.flush()
    pm = ProjectMember(project_id=project.id, user_id=bob.id, role="viewer", accepted_at=_now())
    share = AssetShare(asset_id=asset.id, user_id=bob.id, role="editor")
    session.add_all([pm, share])
    await session.commit()
    assert await effective_role(session, bob, asset) == "editor"


@pytest.mark.asyncio
async def test_project_owner_plus_asset_editor_wins_project_owner(session):
    owner = _user("o")
    bob = _user("b")
    session.add_all([owner, bob])
    await session.flush()
    project = _project(created_by=owner.id)
    session.add(project)
    await session.flush()
    asset = _asset(owner.id, project_id=project.id)
    session.add(asset)
    await session.flush()
    pm = ProjectMember(project_id=project.id, user_id=bob.id, role="owner", accepted_at=_now())
    share = AssetShare(asset_id=asset.id, user_id=bob.id, role="editor")
    session.add_all([pm, share])
    await session.commit()
    assert await effective_role(session, bob, asset) == "project_owner"


@pytest.mark.asyncio
async def test_asset_outside_project_share_only(session):
    """Asset with project_id=NULL: only AssetShare applies."""
    owner = _user("o")
    bob = _user("b")
    other_project_owner = _user("p")
    session.add_all([owner, bob, other_project_owner])
    await session.flush()
    other_project = _project(created_by=other_project_owner.id)
    session.add(other_project)
    await session.flush()
    asset = _asset(owner.id, project_id=None)
    # bob owns a different project; that must not have any effect
    pm = ProjectMember(
        project_id=other_project.id, user_id=bob.id, role="owner", accepted_at=_now()
    )
    session.add_all([asset, pm])
    await session.commit()
    assert await effective_role(session, bob, asset) is None


async def _assigned(session, *, share_role, member_role, accepted=True, home_role=None):
    """Asset with home project H, assigned to project P with `share_role`;
    bob is a member of P with `member_role` (and of H with `home_role`)."""
    owner = _user("o")
    bob = _user("b")
    session.add_all([owner, bob])
    await session.flush()
    home = _project("H", created_by=owner.id)
    assigned = _project("P", created_by=owner.id)
    session.add_all([home, assigned])
    await session.flush()
    asset = _asset(owner.id, project_id=home.id)
    session.add(asset)
    await session.flush()
    session.add_all(
        [
            AssetProjectShare(asset_id=asset.id, project_id=assigned.id, role=share_role),
            ProjectMember(
                project_id=assigned.id,
                user_id=bob.id,
                role=member_role,
                accepted_at=_now() if accepted else None,
            ),
        ]
    )
    if home_role:
        session.add(
            ProjectMember(project_id=home.id, user_id=bob.id, role=home_role, accepted_at=_now())
        )
    await session.commit()
    return bob, asset


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("share_role", "member_role", "expected"),
    [
        ("editor", "owner", "editor"),
        ("editor", "editor", "editor"),
        ("editor", "viewer", "viewer"),
        ("viewer", "owner", "viewer"),
        ("viewer", "editor", "viewer"),
        ("viewer", "viewer", "viewer"),
    ],
)
async def test_project_share_role_is_capped_by_member_role(
    session, share_role, member_role, expected
):
    bob, asset = await _assigned(session, share_role=share_role, member_role=member_role)
    assert await effective_role(session, bob, asset) == expected


@pytest.mark.asyncio
async def test_project_share_never_grants_project_owner(session):
    """An owner of the assigned project gets at most editor, never the home
    project's owner rights."""
    bob, asset = await _assigned(session, share_role="editor", member_role="owner")
    assert await effective_role(session, bob, asset) == "editor"


@pytest.mark.asyncio
async def test_project_share_pending_member_gets_nothing(session):
    bob, asset = await _assigned(session, share_role="editor", member_role="editor", accepted=False)
    assert await effective_role(session, bob, asset) is None


@pytest.mark.asyncio
async def test_home_project_owner_beats_project_share(session):
    bob, asset = await _assigned(
        session, share_role="editor", member_role="editor", home_role="owner"
    )
    assert await effective_role(session, bob, asset) == "project_owner"


@pytest.mark.asyncio
async def test_project_share_editor_beats_direct_viewer_share(session):
    bob, asset = await _assigned(session, share_role="editor", member_role="editor")
    session.add(AssetShare(asset_id=asset.id, user_id=bob.id, role="viewer"))
    await session.commit()
    assert await effective_role(session, bob, asset) == "editor"
