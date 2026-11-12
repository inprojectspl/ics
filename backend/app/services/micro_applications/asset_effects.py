"""What a publication does to the app's asset row besides its version: the
title and description follow the manifest, and an app that never ran leaves
the lists."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Asset, MicroAppEnvironment
from app.services import asset_metadata
from app.services.micro_applications.common import ENVIRONMENT


def follow_manifest(asset: Asset, before: dict[str, Any] | None, after: dict[str, Any]) -> None:
    """Title and description follow the manifest, unless someone changed
    them in ICS since the last release (a rename or a summary by hand
    stays)."""
    old, new = (before or {}).get("metadata", {}), after["metadata"]
    if before is None or asset.title == old.get("title"):
        asset.title = new["title"]
    if asset.summary_source != "human":
        asset_metadata.set_summary(asset, new.get("description"), "agent")


async def withdraw_unborn(session: AsyncSession, asset_id: Any) -> None:
    """An app whose first publication failed never ran and was never
    announced: it leaves the lists (to the trash, where its log stays
    readable) instead of lingering as an empty asset. The operation keeps
    the error for its author; a new plan makes a new app."""
    env = await session.scalar(
        select(MicroAppEnvironment).where(
            MicroAppEnvironment.asset_id == asset_id, MicroAppEnvironment.environment == ENVIRONMENT
        )
    )
    asset = await session.get(Asset, asset_id)
    if (
        asset is not None
        and asset.deleted_at is None
        and (env is None or not env.active_release_id)
    ):
        asset.deleted_at = datetime.now(UTC)
