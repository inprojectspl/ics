"""Relation graph of one project (ADR-0016, ADR-0017): the project's documents
plus visible outside documents an edge reaches (`external`). The caller has
checked membership; the statement count does not depend on project size.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import permissions
from app.models import Asset, AssetExternalRef, Project, User
from app.services.project_shares import in_project_filter
from app.services.relation_graph import edges_touching
from app.services.relation_views import edge_fields, project_nodes

MAX_PROJECT_NODES = 1000
# External references that stand for a unit of work.
TASK_ENTITIES: tuple[str, ...] = ("work_package", "node")


async def _project_documents(
    session: AsyncSession, user: User, project: Project, limit: int
) -> list[Asset]:
    rows = await session.scalars(
        select(Asset)
        .where(in_project_filter(project.id), permissions.visible_assets_filter(user))
        .order_by(Asset.content_updated_at.desc().nulls_last(), Asset.id)
        .limit(limit + 1)
    )
    return list(rows.all())


async def _task_layer(session: AsyncSession, ids: list[UUID]) -> dict[str, Any]:
    refs = (
        await session.scalars(
            select(AssetExternalRef)
            .where(AssetExternalRef.asset_id.in_(ids), AssetExternalRef.entity.in_(TASK_ENTITIES))
            .order_by(AssetExternalRef.created_at, AssetExternalRef.id)
        )
    ).all()
    tasks: dict[str, dict[str, Any]] = {}
    links = []
    for ref in refs:
        key = f"{ref.system}:{ref.entity}:{ref.external_id}"
        task = tasks.setdefault(
            key,
            {
                "id": key,
                "system": ref.system,
                "entity": ref.entity,
                "external_id": ref.external_id,
                "external_scope": ref.external_scope,
                "label": ref.label,
                "url": ref.url,
            },
        )
        task["label"] = task["label"] or ref.label
        task["url"] = task["url"] or ref.url
        links.append(
            {
                "task_id": key,
                "asset_id": str(ref.asset_id),
                "role": ref.role,
                "required": ref.required,
            }
        )
    return {"tasks": list(tasks.values()), "task_links": links}


async def project_graph(
    session: AsyncSession,
    user: User,
    project: Project,
    *,
    include_tasks: bool = False,
    max_nodes: int = MAX_PROJECT_NODES,
) -> dict[str, Any]:
    max_nodes = max(1, min(max_nodes, MAX_PROJECT_NODES))
    docs = await _project_documents(session, user, project, max_nodes)
    truncated = len(docs) > max_nodes
    docs = docs[:max_nodes]
    inside = {a.id for a in docs}

    edges = await edges_touching(session, inside) if inside else []
    outside_ids = {
        end for e in edges for end in (e.source_asset_id, e.target_asset_id) if end not in inside
    }
    outside: list[Asset] = []
    if outside_ids:
        outside = list(
            (
                await session.scalars(
                    select(Asset)
                    .where(Asset.id.in_(outside_ids), permissions.visible_assets_filter(user))
                    .order_by(Asset.title, Asset.id)
                )
            ).all()
        )
    room = max_nodes - len(docs)
    if len(outside) > room:
        truncated = True
        outside = outside[:room]

    nodes_by_id = {a.id: a for a in (*docs, *outside)}
    kept = [
        e for e in edges if e.source_asset_id in nodes_by_id and e.target_asset_id in nodes_by_id
    ]
    fields = await project_nodes(session, user, list(nodes_by_id.values()))

    def node(a: Asset, external: bool) -> dict[str, Any]:
        return {
            **fields[a.id],
            "content_updated_at": (
                a.content_updated_at.isoformat() if a.content_updated_at else None
            ),
            "external": external,
        }

    result: dict[str, Any] = {
        "project": {"id": str(project.id), "slug": project.slug, "name": project.name},
        "nodes": [node(a, False) for a in docs] + [node(a, True) for a in outside],
        "edges": [edge_fields(e, nodes_by_id[e.target_asset_id].version) for e in kept],
        "truncated": truncated,
        "max_nodes": max_nodes,
    }
    if include_tasks:
        result.update(await _task_layer(session, list(inside)))
    return result
