"""Project level links (ADR-0018): external refs mapping an ICS project to
OpenProject / Project Standard projects (one ICS home per external project) and
the ordered key documents. The caller has checked the project role.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, permissions
from app.domain_errors import ConflictError, InvalidInputError, NotFoundError
from app.models import (
    Asset,
    AssetProjectShare,
    Project,
    ProjectExternalRef,
    ProjectKeyDocument,
    User,
)
from app.models.external_refs import PROJECT_EXTERNAL_SYSTEMS
from app.services.relation_views import project_nodes
from app.services.relations import visible_ids

_PROJECT_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")


@dataclass(frozen=True)
class KeyDocumentIn:
    asset_id: UUID
    reason: str | None = None


def _project_not_found() -> NotFoundError:
    return NotFoundError("project_not_found", "project not found")


async def list_external_refs(session: AsyncSession, project: Project) -> list[dict[str, Any]]:
    rows = await session.scalars(
        select(ProjectExternalRef)
        .where(ProjectExternalRef.project_id == project.id)
        .order_by(ProjectExternalRef.system, ProjectExternalRef.external_id)
    )
    return [{"system": r.system, "external_id": r.external_id} for r in rows]


async def set_external_refs(
    session: AsyncSession,
    *,
    actor: User,
    project: Project,
    refs: Sequence[tuple[str, str]],
) -> None:
    """Replace the project's mappings. An external project mapped to another
    ICS project is `project_external_taken`, without saying which one."""
    wanted = set()
    for system, external_id in refs:
        if system not in PROJECT_EXTERNAL_SYSTEMS:
            raise InvalidInputError(
                "external_ref_invalid", "unknown external system", field="system"
            )
        if not _PROJECT_KEY.fullmatch(external_id):
            raise InvalidInputError(
                "external_ref_invalid", "malformed external project id", field="external_id"
            )
        wanted.add((system, external_id))

    current = {
        (r.system, r.external_id): r
        for r in await session.scalars(
            select(ProjectExternalRef).where(ProjectExternalRef.project_id == project.id)
        )
    }
    for key, row in current.items():
        if key not in wanted:
            await session.delete(row)
    for system, external_id in wanted - set(current):
        taken = await session.scalar(
            select(ProjectExternalRef.project_id).where(
                ProjectExternalRef.system == system,
                ProjectExternalRef.external_id == external_id,
            )
        )
        if taken is not None:
            raise _taken()
        session.add(
            ProjectExternalRef(
                project_id=project.id,
                system=system,
                external_id=external_id,
                created_by=actor.id,
            )
        )
    try:
        await session.flush()
    except IntegrityError as exc:  # a concurrent mapping won the unique index
        raise _taken() from exc
    if wanted != set(current):
        await audit.record(
            session,
            actor=actor,
            action="project_external_ref_set",
            target=f"project:{project.id}",
            payload={
                "refs": sorted(f"{s}:{i}" for s, i in wanted),
                "previous": sorted(f"{s}:{i}" for s, i in current),
            },
        )


def _taken() -> ConflictError:
    return ConflictError(
        "project_external_taken", "this external project is already mapped to an ICS project"
    )


async def drop_external_refs(session: AsyncSession, project_id: UUID) -> None:
    """A deleted project must not keep an external project from a new home."""
    await session.execute(
        delete(ProjectExternalRef).where(ProjectExternalRef.project_id == project_id)
    )


async def project_by_external(
    session: AsyncSession, *, actor: User, system: str, external_id: str
) -> tuple[Project, str]:
    """The ICS home of an external project and the caller's role there. No
    mapping and no membership give the same `project_not_found`."""
    project = await session.scalar(
        select(Project)
        .join(ProjectExternalRef, ProjectExternalRef.project_id == Project.id)
        .where(
            ProjectExternalRef.system == system,
            ProjectExternalRef.external_id == external_id,
            Project.deleted_at.is_(None),
        )
    )
    if project is None:
        raise _project_not_found()
    role = await permissions.project_role(session, actor, project)
    if role is None:
        raise _project_not_found()
    return project, role


async def list_key_documents(
    session: AsyncSession, *, actor: User, project: Project
) -> list[dict[str, Any]]:
    """Ordered key documents the caller can see; hidden ones are left out."""
    rows = (
        await session.execute(
            select(ProjectKeyDocument, Asset)
            .join(Asset, Asset.id == ProjectKeyDocument.asset_id)
            .where(ProjectKeyDocument.project_id == project.id)
            .order_by(ProjectKeyDocument.position)
        )
    ).all()
    seen = await visible_ids(session, actor, {a.id for _, a in rows})
    shown = [(k, a) for k, a in rows if a.id in seen]
    nodes = await project_nodes(session, actor, [a for _, a in shown])
    return [
        {**nodes[a.id], "asset_id": str(a.id), "position": k.position, "reason": k.reason}
        for k, a in shown
    ]


async def _may_pin(session: AsyncSession, actor: User, project: Project, asset: Asset) -> bool:
    if asset.project_id == project.id:
        return True
    assigned = await session.get(AssetProjectShare, (asset.id, project.id))
    if assigned is not None:
        return True
    return await permissions.effective_role(session, actor, asset) is not None


async def set_key_documents(
    session: AsyncSession,
    *,
    actor: User,
    project: Project,
    documents: Sequence[KeyDocumentIn],
) -> None:
    """Replace the ordered list. A document must belong to the project, be
    assigned to it, or be visible to the actor; otherwise it is reported as
    missing. A repeated document keeps its first position."""
    ordered: list[KeyDocumentIn] = []
    for doc in documents:
        if all(d.asset_id != doc.asset_id for d in ordered):
            ordered.append(doc)
    for doc in ordered:
        asset = await session.get(Asset, doc.asset_id)
        if asset is None or asset.deleted_at is not None:
            raise NotFoundError("asset_not_found", "asset not found")
        if not await _may_pin(session, actor, project, asset):
            raise NotFoundError("asset_not_found", "asset not found")

    await session.execute(
        delete(ProjectKeyDocument).where(ProjectKeyDocument.project_id == project.id)
    )
    session.add_all(
        ProjectKeyDocument(
            project_id=project.id, asset_id=doc.asset_id, position=i, reason=doc.reason
        )
        for i, doc in enumerate(ordered)
    )
    await session.flush()
    await audit.record(
        session,
        actor=actor,
        action="project_key_documents_set",
        target=f"project:{project.id}",
        payload={"assets": [str(d.asset_id) for d in ordered]},
    )
