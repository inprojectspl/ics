"""RFC 7591 Dynamic Client Registration: public clients only, rate-limited."""

from __future__ import annotations

import json
import time
import uuid
from typing import Annotated

from fastapi import Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app import ratelimit
from app.config import Settings, get_settings
from app.db import get_session
from app.errors import ApiError
from app.models import OAuthClient
from app.redis_client import get_redis

from ._router import _issuer, router


@router.post("/register")
async def dynamic_register(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    redis = get_redis()
    ip = request.client.host if request.client else "0.0.0.0"
    if not await ratelimit.check_and_incr(redis, ratelimit.OAUTH_DCR, ip):
        raise ApiError(status.HTTP_429_TOO_MANY_REQUESTS, "rate_limited", "rate_limited")

    body = json.loads((await request.body()) or b"{}")
    name = body.get("client_name") or "Dynamic MCP client"
    redirect_uris = body.get("redirect_uris") or []
    if not isinstance(redirect_uris, list) or not redirect_uris:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, "invalid_redirect_uri", "redirect_uris required"
        )
    client_id_str = f"dyn-{uuid.uuid4().hex[:16]}"
    audience = settings.mcp_resource_uri or _issuer(settings)
    rec = OAuthClient(
        client_id=client_id_str,
        client_secret_hash=None,
        name=name,
        client_type="public",
        redirect_uris=redirect_uris,
        allowed_scopes=["ics"],
        allowed_audiences=[audience],
        is_dynamic=True,
    )
    session.add(rec)
    await session.commit()
    iss = _issuer(settings)
    return JSONResponse(
        {
            "client_id": client_id_str,
            "client_id_issued_at": int(time.time()),
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "redirect_uris": redirect_uris,
            "registration_client_uri": f"{iss}/api/auth/oauth/clients/{client_id_str}",
        },
        status_code=201,
    )
