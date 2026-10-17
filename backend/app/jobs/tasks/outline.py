"""Arq tasks: rebuild `Asset.outline_json` (built by
`services.outline.build_outline_payload`) and sweep stale outlines."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from app.config import get_settings
from app.db import SessionLocal
from app.models import Asset
from app.services.outline import build_outline_payload


async def rebuild_outline(ctx: dict, asset_id_str: str) -> dict:
    asset_id = UUID(asset_id_str)
    settings = get_settings()
    async with SessionLocal() as session:
        asset = await session.get(Asset, asset_id)
        if asset is None or asset.deleted_at is not None:
            return {"asset_id": asset_id_str, "skipped": "deleted_or_missing"}
        asset.outline_status = "building"
        built_version = asset.version
        await session.commit()
    try:
        outline = await build_outline_payload(asset, settings)
    except Exception as e:
        async with SessionLocal() as session:
            asset = await session.get(Asset, asset_id)
            if asset is not None:
                asset.outline_status = "failed"
                asset.outline_error = f"{type(e).__name__}: {e}"
                await session.commit()
        return {"asset_id": asset_id_str, "error": str(e)}

    async with SessionLocal() as session:
        asset = await session.get(Asset, asset_id)
        if asset is None:
            return {"asset_id": asset_id_str, "skipped": "deleted_during_build"}
        asset.outline_json = outline
        # A version committed during the build is not covered by this
        # outline: keep it stale so the sweeper builds it again.
        asset.outline_version = built_version
        asset.outline_status = "fresh" if asset.version == built_version else "stale"
        asset.outline_built_at = datetime.now(UTC)
        asset.outline_error = None
        await session.commit()
    return {"asset_id": asset_id_str, "outline_version": asset.outline_version}


async def outline_stale_sweeper(ctx: dict) -> dict:
    """Requeue outlines stuck in `building` for 5+ minutes (worker crash or
    deploy) and outlines behind `version` (writes that did not enqueue)."""
    from datetime import timedelta

    from sqlalchemy import or_, select

    cutoff = datetime.now(UTC) - timedelta(minutes=5)
    async with SessionLocal() as session:
        rows = (
            await session.scalars(
                select(Asset).where(
                    Asset.deleted_at.is_(None),
                    or_(
                        (Asset.outline_status == "building") & (Asset.updated_at < cutoff),
                        (Asset.outline_status != "fresh")
                        & (
                            Asset.outline_version.is_(None)
                            | (Asset.outline_version != Asset.version)
                        ),
                    ),
                )
            )
        ).all()
        recovered: list[str] = []
        for asset in rows:
            if asset.outline_status == "building":
                asset.outline_status = "stale"
            recovered.append(str(asset.id))
        await session.commit()
    if recovered:
        from app.jobs.queue import get_pool

        pool = await get_pool()
        await asyncio.gather(
            *[
                pool.enqueue_job("rebuild_outline", aid, _job_id=f"outline:{aid}")
                for aid in recovered
            ]
        )
    return {"recovered": recovered, "count": len(recovered)}
