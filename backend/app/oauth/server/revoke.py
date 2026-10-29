"""RFC 7009 token revocation."""

from __future__ import annotations

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
    # A file part named `token` is as malformed as a missing one.
    if not token_value or not isinstance(token_value, str):
        raise ApiError(status.HTTP_400_BAD_REQUEST, "invalid_request", "invalid_request")
    # `token_type_hint` is optional and may be wrong (RFC 7009, section 2.1),
    # so the token is looked up as a refresh token whatever the hint says.
    rec = await tokens_mod.find_active_refresh(session, tokens_mod.hash_token(token_value))
    if rec is not None:
        # Revoking a refresh token ends the grant: its whole rotation family
        # and the access tokens issued with it.
        await tokens_mod.revoke_refresh_chain(
            session, rec, reason="user_revoke", access_ttl=settings.oauth_access_token_ttl
        )
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
    await tokens_mod.blacklist_jti(session, jti, expires_at_epoch=exp)
    await session.commit()
    return JSONResponse({})
