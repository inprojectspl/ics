"""Centralized ownership/access checks.

Lookups answer 404, not 403, so a guessed identifier does not confirm an asset
exists. `effective_role` takes the strongest of ownership, home-project membership,
direct share and project share on `viewer < editor < project_owner < owner_file`.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from sqlalchemy import ColumnElement, and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.domain_errors import AccessDeniedError, NotFoundError
from app.models import (
    Asset,
    AssetProjectShare,
    AssetShare,
    GitLabBinding,
    Project,
    ProjectMember,
    User,
)

EffectiveRole = Literal["owner_file", "project_owner", "editor", "viewer"]


# Query-level visibility, matching `effective_role` 1:1. EXISTS-based, so the
# predicates compose with any SELECT over Asset without joins.


def _accepted_member_exists(user_id: UUID) -> ColumnElement[bool]:
    """EXISTS: the user is an accepted member of the asset's project.

    A fresh alias, because a caller's own join on this table would otherwise be
    auto-correlated, leaving the EXISTS without a FROM."""
    pm = aliased(ProjectMember)
    return (
        select(pm.id)
        .where(
            pm.project_id == Asset.project_id,
            pm.user_id == user_id,
            pm.accepted_at.is_not(None),
        )
        .correlate(Asset)
        .exists()
    )


def _direct_share_exists(user_id: UUID) -> ColumnElement[bool]:
    """EXISTS: the asset is shared with the user directly (AssetShare).

    Aliased for the same reasons as `_accepted_member_exists`."""
    ash = aliased(AssetShare)
    return (
        select(ash.id)
        .where(ash.asset_id == Asset.id, ash.user_id == user_id)
        .correlate(Asset)
        .exists()
    )


def project_share_member_exists(user_id: UUID, *, editor: bool = False) -> ColumnElement[bool]:
    """EXISTS: the asset is assigned to a project (ADR-0017) where the user is
    an accepted member. With `editor=True`, only a share that yields `editor`:
    an editor share and a project role above viewer."""
    aps = aliased(AssetProjectShare)
    pm = aliased(ProjectMember)
    conditions = [
        aps.asset_id == Asset.id,
        pm.project_id == aps.project_id,
        pm.user_id == user_id,
        pm.accepted_at.is_not(None),
    ]
    if editor:
        conditions += [aps.role == "editor", pm.role.in_(("owner", "editor"))]
    return select(aps.asset_id).where(*conditions).correlate(Asset).exists()


def shared_with_user_filter(user: User) -> ColumnElement[bool]:
    """Assets visible to the user through someone else's channel: project
    membership, a direct share or a project share, excluding ownership.
    Scope filter for `shared_with_me`."""
    return or_(
        _accepted_member_exists(user.id),
        _direct_share_exists(user.id),
        project_share_member_exists(user.id),
    )


def visible_assets_filter(user: User) -> ColumnElement[bool]:
    """Query-level "effective_role returns anything", excluding soft-deleted rows.
    Every listing and search path uses it (guarded by `test_visibility_parity.py`)."""
    not_deleted = Asset.deleted_at.is_(None)
    if user.acts_as_admin:
        return not_deleted
    return and_(
        not_deleted,
        or_(Asset.owner_id == user.id, shared_with_user_filter(user)),
    )


def _direct_editor_share_exists(user_id: UUID) -> ColumnElement[bool]:
    """EXISTS: a direct AssetShare with role editor."""
    ash = aliased(AssetShare)
    return (
        select(ash.id)
        .where(ash.asset_id == Asset.id, ash.user_id == user_id, ash.role == "editor")
        .correlate(Asset)
        .exists()
    )


def graph_accessible_assets_filter(user: User) -> ColumnElement[bool]:
    """Assets whose relations the user may read (ADR-0016, section 5): any project
    route or editor from any source; a direct viewer share alone is not enough."""
    not_deleted = Asset.deleted_at.is_(None)
    if user.acts_as_admin:
        return not_deleted
    return and_(
        not_deleted,
        or_(
            Asset.owner_id == user.id,
            _accepted_member_exists(user.id),
            project_share_member_exists(user.id),
            _direct_editor_share_exists(user.id),
        ),
    )


_ROLE_RANK: dict[str, int] = {
    "viewer": 1,
    "editor": 2,
    "project_owner": 3,
    "owner_file": 4,
}


def _rank(role: EffectiveRole | str | None) -> int:
    if role is None:
        return 0
    return _ROLE_RANK.get(role, 0)


def _meets(role: EffectiveRole | None, min_role: EffectiveRole) -> bool:
    return _rank(role) >= _rank(min_role)


def is_read_only(role: EffectiveRole) -> bool:
    """A role below editor. Rank-based so a future read-only role, or an unknown one
    (rank 0), still hits the visitor gates: fail-closed."""
    return not _meets(role, "editor")


# Raw `ProjectMember.role` / `AssetShare.role` values (no project_owner /
# owner_file distinction; those exist only on the EffectiveRole lattice).
MEMBER_ROLE_RANK: dict[str, int] = {"viewer": 1, "editor": 2, "owner": 3}


def pick_strongest_member_role(*roles: str | None) -> str | None:
    """Max of raw member roles ('viewer'/'editor'/'owner'). None inputs ignored."""
    candidates = [r for r in roles if r]
    if not candidates:
        return None
    return max(candidates, key=lambda r: MEMBER_ROLE_RANK.get(r, 0))


_MEMBER_TO_EFFECTIVE: dict[str, EffectiveRole] = {
    "owner": "project_owner",
    "editor": "editor",
    "viewer": "viewer",
}


async def _accepted_member_role(
    session: AsyncSession, user_id: UUID, project_id: UUID
) -> str | None:
    return await session.scalar(
        select(ProjectMember.role).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
            ProjectMember.accepted_at.is_not(None),
        )
    )


async def effective_role(session: AsyncSession, user: User, asset: Asset) -> EffectiveRole | None:
    """Compute the strongest role `user` holds on `asset`. None = no access."""
    if user.acts_as_admin:
        return "owner_file"
    if asset.owner_id == user.id:
        return "owner_file"

    best: EffectiveRole | None = None

    if asset.project_id is not None:
        member_role = await _accepted_member_role(session, user.id, asset.project_id)
        if member_role is not None:
            best = _MEMBER_TO_EFFECTIVE.get(member_role)

    share = (
        await session.execute(
            select(AssetShare).where(
                AssetShare.asset_id == asset.id,
                AssetShare.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if share is not None:
        candidate: EffectiveRole = "editor" if share.role == "editor" else "viewer"
        if _rank(candidate) > _rank(best):
            best = candidate

    if _rank(best) < _rank("editor"):
        # Project shares yield at most editor, capped by the member's role.
        roles = (await session.execute(_project_share_roles(user.id, asset.id))).all()
        for share_role, member_role in roles:
            candidate = cap_project_share_role(share_role, member_role)
            if _rank(candidate) > _rank(best):
                best = candidate

    return best


def _project_share_roles(user_id: UUID, asset_id: UUID):
    """(share role, member role) for each project share of the asset where the
    user is an accepted member of the assigned project."""
    return (
        select(AssetProjectShare.role, ProjectMember.role)
        .join(ProjectMember, ProjectMember.project_id == AssetProjectShare.project_id)
        .where(
            AssetProjectShare.asset_id == asset_id,
            ProjectMember.user_id == user_id,
            ProjectMember.accepted_at.is_not(None),
        )
    )


def cap_project_share_role(share_role: str, member_role: str) -> Literal["editor", "viewer"]:
    """Role a project share yields (ADR-0017): at most editor, and editor only
    to a member above viewer of the assigned project."""
    return "editor" if share_role == "editor" and member_role != "viewer" else "viewer"


async def has_graph_access(session: AsyncSession, user: User, asset: Asset) -> bool:
    """Graph access predicate (ADR-0016, section 5) for one asset, evaluated
    through `graph_accessible_assets_filter` so the two cannot drift. Content
    access is not enough: a direct viewer share alone gives no graph access."""
    accessible = exists().where(Asset.id == asset.id, graph_accessible_assets_filter(user))
    return bool(await session.scalar(select(accessible)))


async def _load_asset(
    session: AsyncSession, slug: str | None, asset_id: UUID | None, caller: str
) -> Asset | None:
    """The asset by slug or id; None when missing or soft-deleted."""
    if slug is not None:
        asset = await session.scalar(select(Asset).where(Asset.slug == slug))
    elif asset_id is not None:
        asset = await session.get(Asset, asset_id)
    else:
        raise ValueError(f"{caller} requires slug or asset_id")
    return None if asset is None or asset.deleted_at is not None else asset


async def get_graph_asset(
    session: AsyncSession, user: User, *, slug: str | None = None, asset_id: UUID | None = None
) -> Asset:
    """The asset, if the user has graph access to it. No graph access is the
    same 404 as a missing asset."""
    asset = await _load_asset(session, slug, asset_id, "get_graph_asset")
    if asset is None or not await has_graph_access(session, user, asset):
        raise NotFoundError("asset_not_found", "asset not found")
    return asset


async def visible_role(
    session: AsyncSession, user: User, asset: Asset | None
) -> EffectiveRole | None:
    """The user's role on `asset`; None when it is missing, soft-deleted or
    not visible to them."""
    if asset is None or asset.deleted_at is not None:
        return None
    return await effective_role(session, user, asset)


async def can_edit(session: AsyncSession, user: User, asset: Asset | None) -> bool:
    """The asset exists and the user holds at least editor on it."""
    role = await visible_role(session, user, asset)
    return role is not None and not is_read_only(role)


async def get_asset_with_role(
    session: AsyncSession,
    *,
    user: User,
    min_role: EffectiveRole,
    slug: str | None = None,
    asset_id: UUID | None = None,
) -> tuple[Asset, EffectiveRole]:
    """Fetch asset and verify user has at least `min_role`. 404 if not."""
    asset = await _load_asset(session, slug, asset_id, "get_asset_with_role")
    if asset is None:
        raise NotFoundError("asset_not_found", "asset not found")

    role = await effective_role(session, user, asset)
    if not _meets(role, min_role):
        raise NotFoundError("asset_not_found", "asset not found")
    assert role is not None
    return asset, role


# `get_owned_asset_*` admit editor and above (read-only collaborators get 404);
# `get_viewable_asset_*` admit viewers. Owner-only operations (share links,
# deletion) must also check for `owner_file` or `project_owner` at the endpoint.


async def get_asset_by_slug_or_404(session: AsyncSession, slug: str) -> Asset:
    asset = (await session.execute(select(Asset).where(Asset.slug == slug))).scalar_one_or_none()
    if asset is None or asset.deleted_at is not None:
        raise NotFoundError("asset_not_found", "asset not found")
    return asset


async def get_owned_asset_by_slug(session: AsyncSession, slug: str, user: User) -> Asset:
    asset, _ = await get_asset_with_role(
        session,
        user=user,
        min_role="editor",
        slug=slug,
    )
    return asset


async def get_viewable_asset_by_slug(
    session: AsyncSession, slug: str, user: User
) -> tuple[Asset, EffectiveRole]:
    """Asset for read endpoints, with the role for call sites that gate viewers
    (e.g. the critical html_bundle visitor gate)."""
    return await get_asset_with_role(session, user=user, min_role="viewer", slug=slug)


async def get_owned_asset_by_id(session: AsyncSession, asset_id: UUID, user: User) -> Asset:
    asset, _ = await get_asset_with_role(
        session,
        user=user,
        min_role="editor",
        asset_id=asset_id,
    )
    return asset


async def get_viewable_asset_by_id(
    session: AsyncSession, asset_id: UUID, user: User
) -> tuple[Asset, EffectiveRole]:
    """`get_viewable_asset_by_slug` by UUID; the role lets callers hide editor-only
    fields (storage path, the author's full e-mail)."""
    return await get_asset_with_role(session, user=user, min_role="viewer", asset_id=asset_id)


async def get_owned_binding(session: AsyncSession, binding_id: UUID, user: User) -> GitLabBinding:
    binding = await session.get(GitLabBinding, binding_id)
    if binding is None:
        raise NotFoundError("binding_not_found", "binding not found")
    asset = await session.get(Asset, binding.asset_id)
    if asset is None or asset.deleted_at is not None:
        raise NotFoundError("binding_not_found", "binding not found")
    role = await effective_role(session, user, asset)
    # Bindings remain owner/project_owner only: they ship CI keys, not
    # day-to-day edits.
    if role not in ("owner_file", "project_owner"):
        raise NotFoundError("binding_not_found", "binding not found")
    return binding


def can_share_externally(role: EffectiveRole | None) -> bool:
    """Allowed to create public ShareLinks or per-user AssetShares of
    someone else's file: owner of the file OR project owner."""
    return role in ("owner_file", "project_owner")


async def project_role(session: AsyncSession, user: User, project: Project) -> str | None:
    """The user's raw role in the project ('owner' / 'editor' / 'viewer'): an
    acting admin counts as owner, anyone else needs an accepted membership.
    None for a non-member."""
    if user.acts_as_admin:
        return "owner"
    return await _accepted_member_role(session, user.id, project.id)


async def assert_project_contributor(
    session: AsyncSession, user: User, project_id: UUID
) -> Project:
    """Resolve a project the caller may add content to (admin, owner or editor).

    404 when missing or soft-deleted, 403 otherwise.
    """
    project = await session.get(Project, project_id)
    if project is None or project.deleted_at is not None:
        raise NotFoundError("project_not_found", "project not found")
    if await project_role(session, user, project) not in ("owner", "editor"):
        raise AccessDeniedError(
            "project_role_required",
            "you must be an owner or editor of the target project",
        )
    return project


async def get_shareable_asset(
    session: AsyncSession, asset_id: UUID, user: User
) -> tuple[Asset, EffectiveRole]:
    """Asset + role, where the user may share it externally.

    404 for a missing or soft-deleted asset, 403 for any role short of sharing.
    """
    asset = await session.get(Asset, asset_id)
    if asset is None or asset.deleted_at is not None:
        raise NotFoundError("asset_not_found", "asset not found")
    role = await effective_role(session, user, asset)
    if not can_share_externally(role):
        raise AccessDeniedError("share_forbidden", "you cannot share this asset")
    assert role is not None
    return asset, role
