"""RFC 7009 token revocation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request, status
from fastapi.responses import JSONResponse
from joserfc.errors import JoseError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.errors import ApiError
from app.oauth import tokens as tokens_mod

from ._router import router


@router.post("/revoke")
async def revoke_token(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    form = await request.form()
    token_value = form.get("token")
    hint = form.get("token_type_hint")
    # A file part named `token` is as malformed as a missing one.
    if not token_value or not isinstance(token_value, str):
        raise ApiError(status.HTTP_400_BAD_REQUEST, "invalid_request", "invalid_request")
    if hint == "refresh_token":
        rec = await tokens_mod.find_active_refresh(session, tokens_mod.hash_token(token_value))
        if rec and rec.revoked_at is None:
            rec.revoked_at = datetime.now(UTC)
            rec.revocation_reason = "user_revoke"
            await session.commit()
        return JSONResponse({})
    # Otherwise try access JWT. Audience unknown to revoke endpoint: verify
    # the signature, then read jti+exp and blacklist. Claim rules stay off:
    # a token issued for another resource is still ours to revoke.
    try:
        claims = tokens_mod.decode_access_jwt(settings, token_value).claims
        jti = claims.get("jti")
        exp = int(claims["exp"]) if claims.get("exp") else None
    except (JoseError, ValueError, TypeError):
        # RFC 7009 returns 200 even on a bad token (info-leak guard).
        return JSONResponse({})
    if not jti or exp is None:
        return JSONResponse({})
    # Only token errors are swallowed above: a failed write must surface as
    # a 5xx, or the client believes a still-valid token is revoked.
    await tokens_mod.blacklist_jti(session, jti, exp)
    await session.commit()
    return JSONResponse({})
