"""API keys of cloud OCR runs (ADR-0021): kept only in Redis, encrypted with a
key derived from `ICS_SECRET_KEY`, for the length of the run plus a margin.
A key never reaches the database, the audit log, the job arguments or the logs.
"""

from __future__ import annotations

from app import secret_box
from app.config import Settings
from app.redis_client import get_redis

_PURPOSE = "ics-ocr-api-key"


def _key(asset_id: object, version: int) -> str:
    return f"ocr:api-key:{asset_id}:{version}"


async def store(asset_id: object, version: int, api_key: str, settings: Settings) -> None:
    # Long enough for a run that waits in the queue and uses its whole budget.
    ttl = settings.ocr_timeout_seconds + 3600
    token = secret_box.encrypt(settings, _PURPOSE, api_key)
    await get_redis().set(_key(asset_id, version), token, ex=ttl)


async def load(asset_id: object, version: int, settings: Settings) -> str | None:
    token = await get_redis().get(_key(asset_id, version))
    if not token:
        return None
    return secret_box.decrypt(settings, _PURPOSE, token)


async def delete(asset_id: object, version: int) -> None:
    await get_redis().delete(_key(asset_id, version))
