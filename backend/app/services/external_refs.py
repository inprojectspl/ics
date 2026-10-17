"""Links from documents to tasks in external systems (ADR-0018). ICS cannot
verify the task, so `label` is an untrusted plain-text snapshot. A link grants
no access: reading needs graph access to the asset, writing needs editor.
"""

from __future__ import annotations

import re
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, permissions
from app.domain_errors import ConflictError, InvalidInputError, LimitExceededError, NotFoundError
from app.models import Asset, AssetExternalRef, Project, User
from app.models.external_refs import EXTERNAL_ENTITIES, EXTERNAL_ROLES, EXTERNAL_SYSTEMS
from app.services.project_shares import in_project_filter
from app.services.relations import origin_for_transport

MAX_REFS_PER_ASSET = 100
LABEL_MAX_CHARS = 300
_OP_WORK_PACKAGE = re.compile(r"[0-9]{1,12}")
_PS_NODE = re.compile(r"n-[a-z0-9]{1,64}")
# Any other key: one token of printable ASCII, no spaces.
_GENERIC_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/#-]{0,199}")
_SCOPE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")

Origin = Literal["manual", "agent", "integration"]


def _invalid(detail: str, field: str) -> InvalidInputError:
    return InvalidInputError("external_ref_invalid", detail, field=field)


def plain_label(label: str | None) -> str | None:
    """The label as one line of plain text; it is only ever displayed."""
    if label is None:
        return None
    text = " ".join(_CONTROL.sub(" ", label).split())[:LABEL_MAX_CHARS]
    return text or None


def validate_key(system: str, entity: str, external_id: str, external_scope: str | None) -> None:
    if system not in EXTERNAL_SYSTEMS:
        raise _invalid("unknown external system", "system")
    if entity not in EXTERNAL_ENTITIES:
        raise _invalid("unknown external entity", "entity")
    if system == "openproject" and entity == "work_package":
        if not _OP_WORK_PACKAGE.fullmatch(external_id):
            raise _invalid("a work package id is a number", "external_id")
    elif system == "project_standard" and entity == "node":
        if not _PS_NODE.fullmatch(external_id):
            raise _invalid("a node id looks like n-<letters and digits>", "external_id")
        if not external_scope:
            raise _invalid("a node needs its project id as external_scope", "external_scope")
    elif not _GENERIC_ID.fullmatch(external_id):
        raise _invalid("malformed external id", "external_id")
    if external_scope is not None and not _SCOPE.fullmatch(external_scope):
        raise _invalid("malformed external scope", "external_scope")


def ref_fields(ref: AssetExternalRef, asset_version: int) -> dict[str, Any]:
    return {
        "id": str(ref.id),
        "asset_id": str(ref.asset_id),
        "system": ref.system,
        "entity": ref.entity,
        "external_id": ref.external_id,
        "external_scope": ref.external_scope,
        "role": ref.role,
        "required": ref.required,
        "label": ref.label,
        "url": ref.url,
        "asset_path": ref.asset_path,
        "pinned_version": ref.pinned_version,
        "basis_changed": ref.pinned_version is not None and asset_version > ref.pinned_version,
        "note": ref.note,
        "origin": ref.origin,
        "created_at": ref.created_at.isoformat() if ref.created_at else None,
    }


async def list_refs(session: AsyncSession, *, actor: User, asset_id: UUID) -> list[dict[str, Any]]:
    """Links of one asset; no graph access is the same 404 as a missing asset."""
    asset = await permissions.get_graph_asset(session, actor, asset_id=asset_id)
    refs = await session.scalars(
        select(AssetExternalRef)
        .where(AssetExternalRef.asset_id == asset.id)
        .order_by(AssetExternalRef.created_at, AssetExternalRef.id)
    )
    return [ref_fields(r, asset.version) for r in refs]


async def get_ref(session: AsyncSession, *, actor: User, ref_id: UUID) -> dict[str, Any]:
    """One link in the compact agent shape (only the fields that are set),
    under the rule of `list_refs`: graph access to its asset. Anything else
    is the same 404 as a missing link."""
    ref = await session.get(AssetExternalRef, ref_id)
    asset = await session.get(Asset, ref.asset_id) if ref is not None else None
    if (
        ref is None
        or asset is None
        or not await permissions.has_graph_access(session, actor, asset)
    ):
        raise NotFoundError("external_ref_not_found", "external link not found")
    out: dict[str, Any] = {
        "id": str(ref.id),
        "asset": {"slug": asset.slug, "title": asset.title},
        "system": ref.system,
        "external_id": ref.external_id,
    }
    if ref.external_scope:
        out["external_scope"] = ref.external_scope
    out["role"] = ref.role
    if ref.required:
        out["required"] = True
    out |= {key: value for key in ("label", "note") if (value := getattr(ref, key))}
    return out


async def add_ref(
    session: AsyncSession,
    *,
    actor: User,
    asset_id: UUID,
    system: str,
    entity: str,
    external_id: str,
    role: str,
    external_scope: str | None = None,
    required: bool = False,
    label: str | None = None,
    url: str | None = None,
    asset_path: str | None = None,
    pinned_version: int | None = None,
    note: str | None = None,
    origin: Origin | None = None,
    transport: str | None = None,
    client_id_external: str | None = None,
) -> AssetExternalRef:
    """Link the asset to a task. `pinned_version` defaults to the current
    version, so a later version flags `basis_changed`. Does not commit."""
    asset, _ = await permissions.get_asset_with_role(
        session, user=actor, min_role="editor", asset_id=asset_id
    )
    validate_key(system, entity, external_id, external_scope)
    if role not in EXTERNAL_ROLES:
        raise _invalid("unknown link role", "role")
    if url is not None and not url.startswith(("https://", "http://")):
        raise _invalid("the url must be http or https", "url")
    if pinned_version is not None and not 1 <= pinned_version <= asset.version:
        raise _invalid("the pinned version does not exist", "pinned_version")

    existing = await session.scalar(
        select(AssetExternalRef.id).where(
            AssetExternalRef.asset_id == asset.id,
            AssetExternalRef.system == system,
            AssetExternalRef.entity == entity,
            AssetExternalRef.external_id == external_id,
            AssetExternalRef.role == role,
            func.coalesce(AssetExternalRef.asset_path, "") == (asset_path or ""),
        )
    )
    if existing is not None:
        raise ConflictError("external_ref_exists", "this link already exists")
    count = await session.scalar(select(func.count()).where(AssetExternalRef.asset_id == asset.id))
    if int(count or 0) >= MAX_REFS_PER_ASSET:
        raise LimitExceededError("external_ref_limit", "too many external links on this asset")

    ref = AssetExternalRef(
        asset_id=asset.id,
        system=system,
        entity=entity,
        external_id=external_id,
        external_scope=external_scope,
        role=role,
        required=required,
        label=plain_label(label),
        url=url,
        asset_path=asset_path,
        pinned_version=pinned_version if pinned_version is not None else asset.version,
        note=note,
        origin=origin or origin_for_transport(transport),
        created_by=actor.id,
    )
    session.add(ref)
    await session.flush()
    await audit.record(
        session,
        actor=actor,
        action="external_ref_added",
        target=f"asset:{asset.id}",
        payload={
            "ref_id": str(ref.id),
            "system": system,
            "entity": entity,
            "external_id": external_id,
            "role": role,
            "required": required,
            "origin": ref.origin,
        },
        transport=transport,
        client_id_external=client_id_external,
    )
    return ref


async def remove_ref(
    session: AsyncSession,
    *,
    actor: User,
    ref_id: UUID,
    transport: str | None = None,
    client_id_external: str | None = None,
) -> None:
    """Needs editor on the asset; anything less is the same 404 as a missing
    link, so links of documents the actor cannot see stay unknown."""
    ref = await session.get(AssetExternalRef, ref_id)
    if ref is None or not await permissions.can_edit(
        session, actor, await session.get(Asset, ref.asset_id)
    ):
        raise NotFoundError("external_ref_not_found", "external link not found")
    await audit.record(
        session,
        actor=actor,
        action="external_ref_removed",
        target=f"asset:{ref.asset_id}",
        payload={
            "ref_id": str(ref.id),
            "system": ref.system,
            "entity": ref.entity,
            "external_id": ref.external_id,
            "role": ref.role,
        },
        transport=transport,
        client_id_external=client_id_external,
    )
    await session.delete(ref)
    await session.flush()


async def rekey_node_to_work_package(
    session: AsyncSession,
    *,
    actor: User,
    project: Project,
    node_scope: str,
    node_id: str,
    work_package_id: str,
) -> dict[str, int]:
    """Move the links of a PS node to the OP work package created for it
    (ADR-0018, Rekey). Only links on the project's assets (home or assigned)
    that the actor can edit move; a link the work package already has on the
    same asset, role and path is dropped instead of duplicated. The caller
    has checked that the actor owns the project. Does not commit."""
    validate_key("project_standard", "node", node_id, node_scope)
    validate_key("openproject", "work_package", work_package_id, None)
    rows = (
        await session.execute(
            select(AssetExternalRef, Asset)
            .join(Asset, Asset.id == AssetExternalRef.asset_id)
            .where(
                AssetExternalRef.system == "project_standard",
                AssetExternalRef.entity == "node",
                AssetExternalRef.external_scope == node_scope,
                AssetExternalRef.external_id == node_id,
                Asset.deleted_at.is_(None),
                in_project_filter(project.id),
            )
        )
    ).all()
    moved = merged = 0
    for ref, asset in rows:
        if not await permissions.can_edit(session, actor, asset):
            continue
        duplicate = await session.scalar(
            select(AssetExternalRef.id).where(
                AssetExternalRef.asset_id == asset.id,
                AssetExternalRef.system == "openproject",
                AssetExternalRef.entity == "work_package",
                AssetExternalRef.external_id == work_package_id,
                AssetExternalRef.role == ref.role,
                func.coalesce(AssetExternalRef.asset_path, "") == func.coalesce(ref.asset_path, ""),
            )
        )
        if duplicate is not None:
            await session.delete(ref)
            merged += 1
            continue
        ref.system, ref.entity = "openproject", "work_package"
        ref.external_id, ref.external_scope = work_package_id, None
        moved += 1
    await session.flush()
    await audit.record(
        session,
        actor=actor,
        action="external_refs_rekeyed",
        target=f"project:{project.id}",
        payload={
            "from": f"project_standard:{node_scope}:{node_id}",
            "to": f"openproject:{work_package_id}",
            "moved": moved,
            "merged": merged,
        },
    )
    return {"moved": moved, "merged": merged}
