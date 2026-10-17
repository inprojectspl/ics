"""`/token` endpoint: dispatches between authorization_code + refresh_token grants."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, ratelimit
from app.config import Settings, get_settings
from app.db import get_session
from app.errors import ApiError
from app.models import OAuthAuthCode, OAuthClient, User
from app.oauth import clients as clients_mod
from app.oauth import tokens as tokens_mod

from ._router import _enforce_ip_limit, _verify_pkce, router


@router.post("/token")
async def token_endpoint(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> JSONResponse:
    await _enforce_ip_limit(request, ratelimit.OAUTH_TOKEN)
    form = await request.form()
    grant_type = form.get("grant_type")
    if grant_type == "authorization_code":
        return await _grant_authorization_code(form, settings, session)
    if grant_type == "refresh_token":
        return await _grant_refresh(form, settings, session)
    raise ApiError(status.HTTP_400_BAD_REQUEST, "unsupported_grant_type", "unsupported_grant_type")


async def _grant_authorization_code(
    form, settings: Settings, session: AsyncSession
) -> JSONResponse:
    code = form.get("code")
    client_id_str = form.get("client_id")
    redirect_uri = form.get("redirect_uri")
    code_verifier = form.get("code_verifier")
    resource = form.get("resource")
    if not all([code, client_id_str, redirect_uri, code_verifier, resource]):
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, "invalid_request", "invalid_request: missing fields"
        )
    code_hash = tokens_mod.hash_token(code)
    row = await session.scalar(select(OAuthAuthCode).where(OAuthAuthCode.code_hash == code_hash))
    if row is None or row.used_at is not None:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "invalid_grant", "invalid_grant")
    if row.expires_at < datetime.now(UTC):
        raise ApiError(status.HTTP_400_BAD_REQUEST, "invalid_grant", "invalid_grant: expired")
    if row.redirect_uri != redirect_uri:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, "invalid_grant", "invalid_grant: redirect_uri mismatch"
        )
    client = await clients_mod.get_active_client(session, client_id_str)
    if client is None or client.id != row.client_id:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "unauthorized_client", "unauthorized_client")
    # RFC 8707: resource MUST match
    if resource != row.resource:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, "invalid_target", "invalid_target: resource mismatch"
        )
    if not _verify_pkce(code_verifier, row.code_challenge):
        raise ApiError(status.HTTP_400_BAD_REQUEST, "invalid_grant", "invalid_grant: PKCE mismatch")
    user = await session.get(User, row.user_id)
    if user is None:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "invalid_grant", "invalid_grant: user gone")
    row.used_at = datetime.now(UTC)

    access_jwt, jti = tokens_mod.sign_access_jwt(
        settings=settings,
        user=user,
        client_id_external=client.client_id,
        scopes=list(row.scopes),
        audience=row.resource,
    )
    refresh_raw, _ = await tokens_mod.issue_refresh_token(
        session,
        settings=settings,
        client_uuid=client.id,
        user_id=user.id,
        scopes=list(row.scopes),
        resource=row.resource,
        jwt_id=jti,
    )
    await audit.record(
        session,
        actor=user,
        action="oauth_token_issued",
        target=f"client:{client.client_id}",
        payload={"scopes": list(row.scopes), "grant": "code"},
        client_id_external=client.client_id,
        transport="bearer",
    )
    await session.commit()
    return JSONResponse(
        {
            "access_token": access_jwt,
            "token_type": "Bearer",
            "expires_in": settings.oauth_access_token_ttl,
            "refresh_token": refresh_raw,
            "scope": " ".join(row.scopes),
            "resource": row.resource,
        }
    )


async def _grant_refresh(form, settings: Settings, session: AsyncSession) -> JSONResponse:
    refresh_raw = form.get("refresh_token")
    resource = form.get("resource")
    client_id_str = form.get("client_id")
    if not refresh_raw:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, "invalid_request", "invalid_request: refresh_token"
        )
    rec = await tokens_mod.find_active_refresh(session, tokens_mod.hash_token(refresh_raw))
    if rec is None:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "invalid_grant", "invalid_grant")

    # A rotated token presented again means it leaked: revoke the whole chain.
    if rec.revoked_at is not None or rec.rotated_at is not None:
        await tokens_mod.revoke_refresh_chain(session, rec, reason="reuse_detected")
        await session.commit()
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, "invalid_grant", "invalid_grant: reuse detected"
        )
    if rec.expires_at < datetime.now(UTC):
        raise ApiError(status.HTTP_400_BAD_REQUEST, "invalid_grant", "invalid_grant: expired")
    client = await session.get(OAuthClient, rec.client_id)
    if client is None or client.revoked_at is not None:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "unauthorized_client", "unauthorized_client")
    if client_id_str and client_id_str != client.client_id:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "invalid_grant", "client_id mismatch")
    target_resource = resource or rec.resource
    if target_resource != rec.resource:
        # RFC 8707: refresh cannot upgrade audience
        raise ApiError(status.HTTP_400_BAD_REQUEST, "invalid_target", "invalid_target")

    user = await session.get(User, rec.user_id)
    if user is None:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "invalid_grant", "invalid_grant: user gone")

    now = datetime.now(UTC)
    rec.rotated_at = now
    rec.revoked_at = now
    rec.revocation_reason = "rotated"
    access_jwt, new_jti = tokens_mod.sign_access_jwt(
        settings=settings,
        user=user,
        client_id_external=client.client_id,
        scopes=list(rec.scopes),
        audience=rec.resource,
    )
    new_refresh_raw, _new_rec = await tokens_mod.issue_refresh_token(
        session,
        settings=settings,
        client_uuid=client.id,
        user_id=user.id,
        scopes=list(rec.scopes),
        resource=rec.resource,
        jwt_id=new_jti,
        parent_id=rec.id,
    )
    await audit.record(
        session,
        actor=user,
        action="oauth_token_refreshed",
        target=f"client:{client.client_id}",
        payload={"scopes": list(rec.scopes), "grant": "refresh"},
        client_id_external=client.client_id,
        transport="bearer",
    )
    await session.commit()
    return JSONResponse(
        {
            "access_token": access_jwt,
            "token_type": "Bearer",
            "expires_in": settings.oauth_access_token_ttl,
            "refresh_token": new_refresh_raw,
            "scope": " ".join(rec.scopes),
            "resource": rec.resource,
        }
    )
