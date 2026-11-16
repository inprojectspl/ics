"""Who may do what with a micro-application.

Platform rights come from the existing ICS asset roles:
- `app.use`     an active internal account that can currently see the asset;
- `app.publish` owner of the asset or owner of its home project (an editor
                may prepare a plan but not apply it), or an explicit grant;
- `app.control` the same as publish, or an explicit `app.control` grant;
- `app.access.manage` owner of the asset or of its home project.
Business permissions of the app (`requests.approve`, ...) are separate
grants; no ICS role implies them, not even ownership. A grant names either
one permission or one of the app's roles (`role:<name>`); a role gives what
the active release defines for it, so a new release that changes a role
changes what its holders may do.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import MICRO_APPLICATION
from app.models import (
    Asset,
    MicroAppEnvironment,
    MicroAppGrant,
    MicroAppRelease,
    ProjectMember,
    User,
)
from app.permissions import EffectiveRole, effective_role

PLATFORM_GRANTS = frozenset({"app.publish", "app.control"})
ROLE_PREFIX = "role:"


async def active_release(session: AsyncSession, env: MicroAppEnvironment) -> MicroAppRelease | None:
    if env.active_release_id is None:
        return None
    return await session.get(MicroAppRelease, env.active_release_id)


def declared_permissions(release: MicroAppRelease | None) -> set[str]:
    """Business permissions of the active release: the only ones a grant or
    a share link may give."""
    return set(release.manifest["permissions"]) if release else set()


def declared_roles(release: MicroAppRelease | None) -> dict[str, dict[str, Any]]:
    return release.manifest["roles"] if release else {}


def role_grant(name: str) -> str:
    return ROLE_PREFIX + name


def split_grants(grants: Iterable[str]) -> tuple[list[str], list[str]]:
    """(role names, permissions) of stored grant values, each sorted."""
    roles = sorted(g.removeprefix(ROLE_PREFIX) for g in grants if g.startswith(ROLE_PREFIX))
    return roles, sorted(g for g in grants if not g.startswith(ROLE_PREFIX))


def held_roles(grants: Iterable[str], release: MicroAppRelease | None) -> list[str]:
    """Roles of the release these grants name; dropped roles are left out."""
    defined = declared_roles(release)
    named = (g.removeprefix(ROLE_PREFIX) for g in grants if g.startswith(ROLE_PREFIX))
    return sorted(r for r in named if r in defined)


def expand(grants: Iterable[str], release: MicroAppRelease | None) -> set[str]:
    """The business permissions these grants give under `release`. A role or
    a permission the release no longer declares gives nothing."""
    declared = declared_permissions(release)
    roles = declared_roles(release)
    out: set[str] = set()
    for g in grants:
        if g.startswith(ROLE_PREFIX):
            out.update((roles.get(g.removeprefix(ROLE_PREFIX)) or {}).get("permissions", ()))
        else:
            out.add(g)
    return out & declared


@dataclass(frozen=True)
class Rights:
    role: EffectiveRole | None
    use: bool
    publish: bool
    control: bool
    manage: bool
    prepare: bool
    # Every grant of the user (direct or through a project), roles unexpanded.
    grants: frozenset[str] = frozenset()

    def as_dict(self) -> dict[str, bool]:
        return {
            "use": self.use,
            "publish": self.publish,
            "control": self.control,
            "manage_access": self.manage,
            "prepare": self.prepare,
        }


def is_active_internal(user: User | None) -> bool:
    return user is not None and not user.is_locked and user.role in ("user", "admin")


async def granted_permissions(
    session: AsyncSession, user: User, asset_id: UUID, environment: str = "prod"
) -> set[str]:
    """Grants to the user directly or to a project the user is an accepted
    member of. Evaluated on every request: no cache."""
    member_projects = select(ProjectMember.project_id).where(
        ProjectMember.user_id == user.id, ProjectMember.accepted_at.is_not(None)
    )
    rows = await session.scalars(
        select(MicroAppGrant.permission).where(
            MicroAppGrant.asset_id == asset_id,
            MicroAppGrant.environment == environment,
            or_(MicroAppGrant.user_id == user.id, MicroAppGrant.project_id.in_(member_projects)),
        )
    )
    return set(rows)


_OWNER_LIKE = ("owner_file", "project_owner")


def _publishes(role: str, granted: frozenset[str] | set[str]) -> bool:
    """app.publish: the owner, the project's owner or a grant. Also the rule
    for reading an app's package, its history and comparisons."""
    return role in _OWNER_LIKE or "app.publish" in granted


async def publishes(session: AsyncSession, user: User, asset: Asset, role: str) -> bool:
    """`rights(...).publish` for a caller whose asset role is already known;
    an owner needs no grant lookup."""
    if not is_active_internal(user):
        return False
    if role in _OWNER_LIKE:
        return True
    return _publishes(role, await granted_permissions(session, user, asset.id))


async def history_readable(session: AsyncSession, user: User, asset: Asset, role: str) -> bool:
    """Whether a viewer with `role` may read the asset's version history and
    comparisons: anyone for content; for a micro-application only its
    publishers, since its versions are its package's sources."""
    return asset.kind != MICRO_APPLICATION or await publishes(session, user, asset, role)


async def rights(session: AsyncSession, user: User, asset: Asset) -> Rights:
    if asset.deleted_at is not None or not is_active_internal(user):
        return Rights(None, False, False, False, False, False)
    role = await effective_role(session, user, asset)
    if role is None:
        return Rights(None, False, False, False, False, False)
    granted = frozenset(await granted_permissions(session, user, asset.id))
    owner_like = role in _OWNER_LIKE
    publish = _publishes(role, granted)
    return Rights(
        role=role,
        use=True,
        publish=publish,
        control=publish or "app.control" in granted,
        manage=owner_like,
        prepare=publish or role == "editor",
        grants=granted,
    )
