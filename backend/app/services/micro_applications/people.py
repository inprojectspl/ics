"""Who may use a micro-application and what they may do in it.

Two independent things make a person able to work in an app: opening it
(`app.use`: any role on the asset, here usually a `viewer` share) and the
app's own business permissions (grants), given one by one or through the
roles the app defines. `set_access` sets both for one person or project to
an exact target state, so an agent states the result instead of replaying
panel clicks.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.config import Settings
from app.domain_errors import AccessDeniedError, InvalidInputError, NotFoundError
from app.models import (
    Asset,
    AssetProjectShare,
    AssetShare,
    MicroAppEnvironment,
    MicroAppGrant,
    MicroAppRelease,
    Project,
    ProjectMember,
    User,
)
from app.permissions import effective_role
from app.services.micro_applications import access
from app.services.micro_applications.catalog import permission_catalog, role_catalog
from app.services.micro_applications.common import ENVIRONMENT, load_app
from app.services.micro_applications.hosts import app_url

# ---------- shared checks ----------


async def managed_app(
    session: AsyncSession, user: User, asset_id: Any, *, lock: bool = False
) -> tuple[Asset, MicroAppEnvironment]:
    """The app, if `user` may manage who uses it (`app.access.manage`)."""
    asset, env = await load_app(session, asset_id, lock=lock)
    r = await access.rights(session, user, asset)
    if not r.use:
        raise NotFoundError("not_found", "micro-application not found")
    if not r.manage:
        raise AccessDeniedError("manage_permission_required", "app.access.manage is required")
    return asset, env


def _check_grants(release: MicroAppRelease | None, roles: set[str], permissions: set[str]) -> None:
    defined = access.declared_roles(release)
    unknown_roles = roles - set(defined)
    if unknown_roles:
        raise InvalidInputError(
            "role_unknown",
            f"the application defines no role: {', '.join(sorted(unknown_roles))}",
            field="roles",
            extra={"allowed": list(defined)},
        )
    allowed = access.declared_permissions(release) | set(access.PLATFORM_GRANTS)
    unknown = permissions - allowed
    if unknown:
        raise InvalidInputError(
            "permission_unknown",
            f"the application does not declare: {', '.join(sorted(unknown))}",
            field="permissions",
            extra={"allowed": sorted(allowed)},
        )


def _split(grants: set[str]) -> dict[str, list[str]]:
    roles, permissions = access.split_grants(grants)
    return {"roles": roles, "permissions": permissions}


def _effective(grants: set[str], release: MicroAppRelease | None) -> list[str]:
    """What the grants give now: business permissions with roles expanded,
    plus platform ones."""
    return sorted(access.expand(grants, release) | (grants & access.PLATFORM_GRANTS))


async def _principal(
    session: AsyncSession, user_email: str | None, project_id: UUID | None
) -> User | None:
    """The grantee user (None for a project), validated."""
    if (user_email is None) == (project_id is None):
        raise InvalidInputError(
            "principal_required", "give exactly one of user_email or project_id"
        )
    if user_email is not None:
        grantee = await session.scalar(select(User).where(User.email == user_email.strip().lower()))
        if grantee is None or not access.is_active_internal(grantee):
            raise NotFoundError(
                "user_not_found",
                "no active internal account with this e-mail; invite the person first "
                "(ics_share_grant_user creates an invited account)",
                field="user_email",
            )
        return grantee
    if await session.get(Project, project_id) is None:
        raise NotFoundError("project_not_found", "project not found", field="project_id")
    return None


def _who(grantee: User | None, project_id: UUID | None) -> dict[str, str | None]:
    return {
        "user_id": str(grantee.id) if grantee else None,
        "project_id": str(project_id) if project_id else None,
    }


# ---------- reading ----------


async def _people(
    session: AsyncSession, asset: Asset, release: MicroAppRelease | None, persons: list[User]
) -> list[dict[str, Any]]:
    """Access of several people with a fixed number of queries plus the role
    lookup of each person."""
    ids = [p.id for p in persons]
    grants = list(
        await session.scalars(
            select(MicroAppGrant).where(
                MicroAppGrant.asset_id == asset.id, MicroAppGrant.environment == ENVIRONMENT
            )
        )
    )
    by_project: dict[UUID, set[str]] = {}
    direct: dict[UUID, set[str]] = {}
    for g in grants:
        if g.user_id is not None:
            direct.setdefault(g.user_id, set()).add(g.permission)
        elif g.project_id is not None:
            by_project.setdefault(g.project_id, set()).add(g.permission)
    memberships = (
        (
            await session.execute(
                select(ProjectMember.user_id, ProjectMember.project_id).where(
                    ProjectMember.user_id.in_(ids),
                    ProjectMember.project_id.in_(list(by_project)),
                    ProjectMember.accepted_at.is_not(None),
                )
            )
        ).all()
        if by_project and ids
        else []
    )
    via_projects: dict[UUID, set[str]] = {}
    for user_id, project_id in memberships:
        via_projects.setdefault(user_id, set()).update(by_project[project_id])
    out = []
    for person in persons:
        role = await effective_role(session, person, asset)
        mine = direct.get(person.id, set())
        out.append(
            {
                "email": person.email,
                "display_name": person.display_name,
                "can_open": role is not None
                and access.is_active_internal(person)
                and asset.deleted_at is None,
                "access": "owner" if person.id == asset.owner_id else role,
                # Direct grants: roles and single permissions.
                **_split(mine),
                # Direct grants plus those through projects the person belongs to.
                "effective_permissions": _effective(
                    mine | via_projects.get(person.id, set()), release
                ),
            }
        )
    return out


async def _projects_opening(session: AsyncSession, asset: Asset, ids: list[UUID]) -> set[UUID]:
    """Which of these projects' members can open the app (home or shared)."""
    opened = set(
        await session.scalars(
            select(AssetProjectShare.project_id).where(
                AssetProjectShare.asset_id == asset.id, AssetProjectShare.project_id.in_(ids)
            )
        )
    )
    if asset.project_id in ids:
        opened.add(asset.project_id)
    return opened


async def overview(
    session: AsyncSession, settings: Settings, user: User, asset_id: Any
) -> dict[str, Any]:
    asset, env = await managed_app(session, user, asset_id)
    release = await access.active_release(session, env)
    persons = list(
        await session.scalars(
            select(User).where(
                (User.id == asset.owner_id)
                | User.id.in_(select(AssetShare.user_id).where(AssetShare.asset_id == asset.id))
                | User.id.in_(
                    select(MicroAppGrant.user_id).where(MicroAppGrant.asset_id == asset.id)
                )
            )
        )
    )
    project_rows = (
        await session.execute(
            select(Project.id, Project.name, MicroAppGrant.permission)
            .join(MicroAppGrant, MicroAppGrant.project_id == Project.id)
            .where(MicroAppGrant.asset_id == asset.id)
            .order_by(Project.name, MicroAppGrant.permission)
        )
    ).all()
    held: dict[UUID, tuple[str, set[str]]] = {}
    for pid, name, permission in project_rows:
        held.setdefault(pid, (name, set()))[1].add(permission)
    opening = await _projects_opening(session, asset, list(held))
    projects = [
        {
            "project_id": str(pid),
            "name": name,
            **_split(grants),
            "members_can_open": pid in opening,
        }
        for pid, (name, grants) in held.items()
    ]
    return {
        "asset_id": str(asset.id),
        "title": asset.title,
        "app_url": app_url(settings, env),
        "roles": role_catalog(release),
        "permissions": permission_catalog(release),
        "people": await _people(session, asset, release, persons),
        "projects": projects,
    }


# ---------- changing ----------


def _grant(
    asset: Asset, permission: str, grantee: User | None, project_id: UUID | None, by: User
) -> MicroAppGrant:
    return MicroAppGrant(
        asset_id=asset.id,
        environment=ENVIRONMENT,
        permission=permission,
        user_id=grantee.id if grantee else None,
        project_id=project_id,
        created_by=by.id,
    )


async def set_access(
    session: AsyncSession,
    settings: Settings,
    user: User,
    asset_id: Any,
    *,
    user_email: str | None,
    project_id: UUID | None,
    roles: list[str],
    permissions: list[str],
    can_open: bool | None,
) -> dict[str, Any]:
    """Make the direct grants of one person or project exactly `roles` plus
    `permissions`; with `can_open`, also make sure the person can (True) or
    cannot (False) open the app. Repeating the same call changes nothing."""
    asset, env = await managed_app(session, user, asset_id, lock=True)
    release = await access.active_release(session, env)
    _check_grants(release, set(roles), set(permissions))
    desired = {access.role_grant(r) for r in roles} | set(permissions)
    grantee = await _principal(session, user_email, project_id)
    principal = (
        MicroAppGrant.user_id == grantee.id if grantee else MicroAppGrant.project_id == project_id
    )
    current = {
        g.permission: g
        for g in await session.scalars(
            select(MicroAppGrant).where(
                MicroAppGrant.asset_id == asset.id,
                MicroAppGrant.environment == ENVIRONMENT,
                principal,
            )
        )
    }
    added = sorted(desired - set(current))
    removed = sorted(set(current) - desired)
    target = f"asset:{asset.id}"
    who = _who(grantee, project_id)
    for perm in added:
        session.add(_grant(asset, perm, grantee, project_id, user))
        await audit.record(
            session,
            actor=user,
            action="microapp_grant_added",
            target=target,
            payload={"permission": perm, **who},
        )
    for perm in removed:
        await session.delete(current[perm])
        await audit.record(
            session,
            actor=user,
            action="microapp_grant_removed",
            target=target,
            payload={"permission": perm, **who},
        )
    open_change = None
    if grantee is not None and can_open is not None and grantee.id != asset.owner_id:
        share = await session.scalar(
            select(AssetShare).where(
                AssetShare.asset_id == asset.id, AssetShare.user_id == grantee.id
            )
        )
        if can_open and share is None and await effective_role(session, grantee, asset) is None:
            session.add(
                AssetShare(asset_id=asset.id, user_id=grantee.id, role="viewer", granted_by=user.id)
            )
            await audit.record(
                session,
                actor=user,
                action="asset_share_granted",
                target=target,
                payload={"to_user": str(grantee.id), "role": "viewer", "new_account": False},
            )
            open_change = "viewer_share_added"
        elif not can_open and share is not None and share.role == "viewer":
            await session.delete(share)
            await audit.record(
                session,
                actor=user,
                action="asset_share_revoked",
                target=target,
                payload={"to_user": str(grantee.id), "role": "viewer"},
            )
            open_change = "viewer_share_removed"
    if added or removed:
        env.policy_generation += 1
    await session.commit()
    added_split, removed_split = _split(set(added)), _split(set(removed))
    result: dict[str, Any] = {
        "added": added_split["permissions"],
        "removed": removed_split["permissions"],
        "roles_added": added_split["roles"],
        "roles_removed": removed_split["roles"],
        "open_change": open_change,
    }
    if grantee is not None:
        (person,) = await _people(session, asset, release, [grantee])
        result["person"] = person
        if can_open is False and person["can_open"]:
            # Not through a viewer share this call could remove: say how, so
            # the caller does not assume the person is out.
            result["still_opens_via"] = person["access"]
    else:
        assert project_id is not None
        result["project"] = {
            "project_id": str(project_id),
            **_split(desired),
            "effective_permissions": _effective(desired, release),
            "members_can_open": project_id in await _projects_opening(session, asset, [project_id]),
        }
    return result
