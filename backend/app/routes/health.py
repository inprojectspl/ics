from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(session: Annotated[AsyncSession, Depends(get_session)]) -> dict[str, str]:
    await session.execute(text("SELECT 1"))
    return {"status": "ready"}


@router.get("/health/jobs")
async def jobs_health() -> JSONResponse:
    """Arq worker freshness from its Redis heartbeat key: `ok` while the key
    exists, `unknown` otherwise (always 200)."""
    from app.redis_client import get_redis

    redis = get_redis()
    raw = await redis.get("arq:health-check")
    return JSONResponse({"status": "ok" if raw else "unknown", "heartbeat": raw})


# ---------- MCP Resource Server discovery (RFC 9728) ----------
# Required by the MCP spec (2025-11-25) so clients find the authorization
# server; ICS plays both roles for `mcp_resource_uri`.


@router.get("/.well-known/oauth-protected-resource")
async def protected_resource_metadata(
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    issuer = (settings.oauth_issuer or settings.base_url).rstrip("/")
    return JSONResponse(
        {
            "resource": settings.mcp_resource_uri or issuer,
            "authorization_servers": [issuer],
            "bearer_methods_supported": ["header"],
            "resource_documentation": f"{issuer}/api/auth/oauth/docs",
            "scopes_supported": ["ics"],
        }
    )
