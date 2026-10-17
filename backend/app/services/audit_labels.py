"""Readable names and app links for audit log references (`asset:<uuid>`,
`binding:<uuid>`, `user_id:<uuid>`, `user:<email>`), resolved at read time with one query per
referenced table. Deleted rows keep their name but get no link; a reference to
a row that is gone keeps the raw value.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Asset, GitLabBinding, PersonalAccessToken, Project, ShareLink, User


@dataclass(frozen=True)
class RefInfo:
    label: str
    href: str | None


def _user_href(user_id: UUID) -> str:
    return f"/admin/users?user={user_id}"


Resolver = Callable[[AsyncSession, list[str]], Awaitable[dict[str, RefInfo]]]


def _uuids(values: list[str]) -> list[UUID]:
    out = []
    for v in values:
        try:
            out.append(UUID(v))
        except ValueError:
            continue
    return out


async def _assets(session: AsyncSession, ids: list[str]) -> dict[str, RefInfo]:
    rows = await session.execute(
        select(Asset.id, Asset.title, Asset.slug, Asset.deleted_at).where(Asset.id.in_(_uuids(ids)))
    )
    return {
        str(i): RefInfo(title or slug, None if deleted else f"/v/{slug}")
        for i, title, slug, deleted in rows
    }


async def _users_by_id(session: AsyncSession, ids: list[str]) -> dict[str, RefInfo]:
    rows = await session.execute(select(User.id, User.email).where(User.id.in_(_uuids(ids))))
    return {str(i): RefInfo(email, _user_href(i)) for i, email in rows}


async def _users(session: AsyncSession, values: list[str]) -> dict[str, RefInfo]:
    # `user:` carries an id on targets and an email on actors (`audit.actor_label`).
    emails = [v for v in values if "@" in v]
    ids = _uuids([v for v in values if "@" not in v])
    rows = await session.execute(
        select(User.id, User.email).where(or_(User.id.in_(ids), User.email.in_(emails)))
    )
    wanted = set(values)
    out: dict[str, RefInfo] = {}
    for i, email in rows:
        info = RefInfo(email, _user_href(i))
        out.update({key: info for key in (str(i), email) if key in wanted})
    return out


async def _projects(session: AsyncSession, ids: list[str]) -> dict[str, RefInfo]:
    rows = await session.execute(
        select(Project.id, Project.name, Project.slug).where(Project.id.in_(_uuids(ids)))
    )
    return {str(i): RefInfo(name, f"/projects/{slug}") for i, name, slug in rows}


async def _shares(session: AsyncSession, ids: list[str]) -> dict[str, RefInfo]:
    # A link has no name of its own; the admin needs to know what it shares.
    rows = await session.execute(
        select(ShareLink.id, Asset.title, Asset.slug, Asset.deleted_at)
        .join(Asset, Asset.id == ShareLink.asset_id)
        .where(ShareLink.id.in_(_uuids(ids)))
    )
    return {
        str(i): RefInfo(title or slug, None if deleted else f"/v/{slug}")
        for i, title, slug, deleted in rows
    }


async def _bindings(session: AsyncSession, ids: list[str]) -> dict[str, RefInfo]:
    # Like a share link, a binding is known by the document it syncs.
    rows = await session.execute(
        select(GitLabBinding.id, Asset.title, Asset.slug, Asset.deleted_at)
        .join(Asset, Asset.id == GitLabBinding.asset_id)
        .where(GitLabBinding.id.in_(_uuids(ids)))
    )
    return {
        str(i): RefInfo(title or slug, None if deleted else f"/v/{slug}")
        for i, title, slug, deleted in rows
    }


async def _tokens(session: AsyncSession, ids: list[str]) -> dict[str, RefInfo]:
    rows = await session.execute(
        select(PersonalAccessToken.id, PersonalAccessToken.name).where(
            PersonalAccessToken.id.in_(_uuids(ids))
        )
    )
    return {str(i): RefInfo(name, None) for i, name in rows}


async def _cdn_hosts(_session: AsyncSession, hosts: list[str]) -> dict[str, RefInfo]:
    return {h: RefInfo(h, "/admin/cdn") for h in hosts}


async def _doc_types(_session: AsyncSession, keys: list[str]) -> dict[str, RefInfo]:
    return {k: RefInfo(k, "/admin/doc-types") for k in keys}


_RESOLVERS: dict[str, Resolver] = {
    "asset": _assets,
    "user": _users,
    "user_id": _users_by_id,
    "project": _projects,
    "share": _shares,
    "binding": _bindings,
    "pat": _tokens,
    "cdn": _cdn_hosts,
    "doc_type": _doc_types,
}


# Payload fields that hold an id, and what the id points at. `to`/`from` hold
# a project only on `asset_project_changed` (elsewhere they are task keys).
_PAYLOAD_FIELDS: dict[str, str] = {
    "asset_id": "asset",
    "assets": "asset",
    "source": "asset",
    "target": "asset",
    "project_id": "project",
    "user_id": "user_id",
    "to_user": "user_id",
    "to_user_id": "user_id",
    "from_user_id": "user_id",
}
_ACTION_FIELDS: dict[str, dict[str, str]] = {
    "asset_project_changed": {"to": "project", "from": "project"},
}


def payload_refs(action: str, payload: object) -> dict[str, list[str]]:
    """References held in an event's payload, per field (`asset:<id>` form)."""
    if not isinstance(payload, dict):
        return {}
    fields = {**_PAYLOAD_FIELDS, **_ACTION_FIELDS.get(action, {})}
    out: dict[str, list[str]] = {}
    for key, kind in fields.items():
        value = payload.get(key)
        values = value if isinstance(value, list) else [value]
        refs = [f"{kind}:{v}" for v in values if isinstance(v, str) and v]
        if refs:
            out[key] = refs
    return out


async def resolve_refs(session: AsyncSession, refs: Iterable[str | None]) -> dict[str, RefInfo]:
    """Maps each resolvable reference to its name and link; others are absent."""
    wanted: dict[str, set[str]] = {}
    for ref in refs:
        if not ref:
            continue
        kind, sep, value = ref.partition(":")
        if sep and value and kind in _RESOLVERS:
            wanted.setdefault(kind, set()).add(value)

    out: dict[str, RefInfo] = {}
    for kind, values in wanted.items():
        for value, info in (await _RESOLVERS[kind](session, sorted(values))).items():
            out[f"{kind}:{value}"] = info
    return out
