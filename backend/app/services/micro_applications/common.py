"""Shared helpers of the micro-application services."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import httpx
import ulid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.constants import MICRO_APPLICATION
from app.domain_errors import NotFoundError
from app.models import Asset, MicroAppEnvironment, MicroAppLog

ENVIRONMENT = "prod"
# Error code of every generic content route that refuses this kind.
REQUIRES_AGENT_API = "microapp_requires_agent_api"
SOURCE_RESTRICTED = "microapp_source_restricted"


def new_id(prefix: str) -> str:
    return f"{prefix}_{str(ulid.new()).lower()}"


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def app_host(settings: Settings, asset_hex: str, environment: str = ENVIRONMENT) -> str:
    return f"a-{asset_hex}-{environment}.{settings.microapps_app_host_suffix}"


def app_url(settings: Settings, asset_hex: str, environment: str = ENVIRONMENT) -> str:
    for alias, hex_ in settings.microapps_alias_map.items():
        if hex_ == asset_hex and environment == ENVIRONMENT:
            return f"https://{alias}/"
    return f"{settings.microapps_app_scheme}://{app_host(settings, asset_hex, environment)}/"


async def load_app(
    session: AsyncSession, asset_id: Any, *, lock: bool = False
) -> tuple[Asset, MicroAppEnvironment]:
    asset = await session.get(Asset, asset_id)
    if asset is None or asset.kind != MICRO_APPLICATION or asset.deleted_at is not None:
        raise NotFoundError("not_found", "micro-application not found")
    stmt = select(MicroAppEnvironment).where(
        MicroAppEnvironment.asset_id == asset.id, MicroAppEnvironment.environment == ENVIRONMENT
    )
    if lock:
        stmt = stmt.with_for_update()
    env = await session.scalar(stmt)
    if env is None:
        raise NotFoundError("not_found", "micro-application not found")
    return asset, env


def add_log(
    session: AsyncSession,
    asset_id: Any,
    level: str,
    source: str,
    message: str,
    *,
    release_id: str | None = None,
    request_id: str | None = None,
    fields: dict[str, Any] | None = None,
) -> None:
    session.add(
        MicroAppLog(
            asset_id=asset_id,
            environment=ENVIRONMENT,
            level=level,
            source=source,
            message=message[:1000],
            release_id=release_id,
            request_id=request_id,
            fields=fields or {},
        )
    )


async def broker_admin(
    settings: Settings, method: str, path: str, body: Any = None, timeout: float = 15.0
) -> dict[str, Any]:
    """Call the broker's private admin API. Raises httpx errors to callers
    that decide whether the step is retryable."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.request(
            method,
            f"{settings.microapps_broker_admin_url.rstrip('/')}{path}",
            json=body,
            headers={"x-ics-service-token": settings.microapps_service_token},
        )
        resp.raise_for_status()
        result: dict[str, Any] = resp.json()
        return result
