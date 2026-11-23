"""Arq tasks of automatic Google Sheets syncs (ADR-0031, ADR-0032): a
sweeper every 10 seconds that reads the apps' activity from the platform
database, and one job per link, never two of the same link at once. Both
run on the sheets queue (`app.jobs.sheets_worker`)."""

from __future__ import annotations

from uuid import UUID

import structlog

from app.config import get_settings
from app.db import SessionLocal
from app.services.sheets import auto, grants

log = structlog.get_logger(__name__)


async def sheets_auto_sweeper(ctx: dict) -> dict:
    settings = get_settings()
    if not grants.enabled(settings):
        return {"links": 0}
    async with SessionLocal() as session:
        ids = await auto.due_links(session, settings)
    return {"links": await auto.enqueue(ctx["redis"], settings, ids)}


async def sheets_auto_sync(ctx: dict, link_id: str) -> dict:
    async with SessionLocal() as session:
        outcome = await auto.run(session, get_settings(), UUID(link_id))
    return {"link_id": link_id, "outcome": outcome}
