"""`/authorize` consent endpoints: GET renders form, POST processes decision."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import quote, urlencode

from fastapi import Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, ratelimit, session_store
from app.config import Settings, get_settings
from app.db import get_session
from app.errors import ApiError
from app.i18n import resolve_locale
from app.i18n.request import AcceptLanguage
from app.models import OAuthAuthCode, User
from app.oauth import clients as clients_mod
from app.oauth import scopes as scopes_mod
from app.oauth import state as state_mod
from app.oauth import tokens as tokens_mod
from app.oauth.server.consent_page import render_consent
from app.redis_client import get_redis
from app.session_store import SESSION_KEY, SESSION_SID_KEY

from ._router import _enforce_ip_limit, router


def _redirect_to_login(settings: Settings, request: Request) -> RedirectResponse:
    """Shared redirect for an unauthenticated session on GET /authorize.
    Without a sid, or with a revoked one, send the user to the frontend
    `/#login?next=...` so they return to the same auth URL after login."""
    # Keep only the path and original query: forwarded Host values must never
    # become a post-login destination, and the SPA only accepts relative paths.
    next_path = request.url.path
    if request.url.query:
        next_path += f"?{request.url.query}"
    return RedirectResponse(f"{settings.base_url}/#login?next={quote(next_path, safe='')}")


@router.get("/authorize", response_model=None)
async def authorize_get(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[AsyncSession, Depends(get_session)],
    response_type: str,
    client_id: str,
    redirect_uri: str,
    scope: str,
    code_challenge: str,
    code_challenge_method: str,
    resource: str,
    state: str | None = None,
    nonce: str | None = None,
    accept_language: AcceptLanguage = None,
) -> HTMLResponse | RedirectResponse:
    await _enforce_ip_limit(request, ratelimit.OAUTH_AUTHORIZE)
    # Require an active ICS session (cookie). Reuse the session_store
    # revocation check so /authorize is not a bypass for a revoked cookie.
    user_id_str = request.session.get(SESSION_KEY)
    sid = request.session.get(SESSION_SID_KEY)
    if not user_id_str or not sid:
        return _redirect_to_login(settings, request)
    redis = get_redis()
    if await session_store.is_revoked(redis, sid):
        request.session.clear()
        return _redirect_to_login(settings, request)
    user = await session.get(User, uuid.UUID(user_id_str))
    if user is None:
        raise ApiError(status.HTTP_401_UNAUTHORIZED, "user_not_found", "user not found")
    if user.locked_until and user.locked_until > datetime.now(UTC):
        raise ApiError(status.HTTP_403_FORBIDDEN, "account_locked", "account locked")

    if response_type != "code":
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, "unsupported_response_type", "unsupported_response_type"
        )
    if code_challenge_method != "S256":
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, "invalid_request", "invalid_request: S256 required"
        )
    if not code_challenge or len(code_challenge) < 43:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, "invalid_request", "invalid_request: code_challenge"
        )
    if not resource:
        # RFC 8707: MUST validate resource indicator
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, "invalid_target", "invalid_target: resource missing"
        )

    client = await clients_mod.get_active_client(session, client_id)
    if client is None:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "unauthorized_client", "unauthorized_client")
    if not clients_mod.validate_redirect_uri(client, redirect_uri):
        raise ApiError(status.HTTP_400_BAD_REQUEST, "invalid_redirect_uri", "invalid_redirect_uri")
    if not clients_mod.validate_audience(client, resource):
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, "invalid_target", "invalid_target: resource not allowed"
        )
    requested = scopes_mod.normalize_scope_string(scope)
    granted = scopes_mod.validate_scopes(requested, client.allowed_scopes)
    if not granted:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "invalid_scope", "invalid_scope")

    state_token = state_mod.issue(
        settings,
        {
            "client_id": client_id,
            "user_id": user_id_str,
            "redirect_uri": redirect_uri,
            "scopes": granted,
            "resource": resource,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "nonce": nonce,
            "state": state,
        },
    )
    return HTMLResponse(
        render_consent(
            locale=resolve_locale(user.locale, accept_language=accept_language),
            client_name=client.name,
            user_email=user.email,
            scopes=granted,
            resource=resource,
            redirect_origin=clients_mod.redirect_origin(redirect_uri),
            state_token=state_token,
        )
    )


@router.post("/authorize")
async def authorize_post(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[AsyncSession, Depends(get_session)],
    state_token: Annotated[str, Form()],
    decision: Annotated[str, Form()],
) -> RedirectResponse:
    await _enforce_ip_limit(request, ratelimit.OAUTH_AUTHORIZE)
    payload = state_mod.verify(settings, state_token)
    if payload is None:
        raise ApiError(status.HTTP_403_FORBIDDEN, "invalid_state_token", "invalid_state_token")

    # Cross-check that the logged-in user matches the consent owner and
    # that the session is still valid (not revoked by logout/lockout since
    # the state_token was issued).
    current_user_id = request.session.get(SESSION_KEY)
    current_sid = request.session.get(SESSION_SID_KEY)
    if current_user_id != payload["user_id"]:
        raise ApiError(status.HTTP_403_FORBIDDEN, "session_mismatch", "session_mismatch")
    if not current_sid or await session_store.is_revoked(get_redis(), current_sid):
        raise ApiError(status.HTTP_403_FORBIDDEN, "session_revoked", "session_revoked")

    client = await clients_mod.get_active_client(session, payload["client_id"])
    if client is None:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "unauthorized_client", "unauthorized_client")

    redirect = payload["redirect_uri"]
    upstream_state = payload.get("state")
    sep = "&" if "?" in redirect else "?"

    if decision != "allow":
        params = {"error": "access_denied"}
        if upstream_state is not None:
            params["state"] = upstream_state
        return RedirectResponse(f"{redirect}{sep}{urlencode(params)}", status_code=302)

    from app.slug import generate_token

    raw_code = generate_token(32)
    code_hash = tokens_mod.hash_token(raw_code)
    session.add(
        OAuthAuthCode(
            code_hash=code_hash,
            client_id=client.id,
            user_id=uuid.UUID(payload["user_id"]),
            redirect_uri=redirect,
            scopes=payload["scopes"],
            resource=payload["resource"],
            code_challenge=payload["code_challenge"],
            code_challenge_method=payload["code_challenge_method"],
            nonce=payload.get("nonce"),
            expires_at=datetime.now(UTC) + timedelta(seconds=settings.oauth_authcode_ttl),
        )
    )
    await audit.record(
        session,
        actor=await session.get(User, uuid.UUID(payload["user_id"])),
        action="oauth_consent_granted",
        target=f"client:{client.client_id}",
        payload={"scopes": payload["scopes"], "resource": payload["resource"]},
    )
    await session.commit()
    params = {"code": raw_code}
    if upstream_state is not None:
        params["state"] = upstream_state
    return RedirectResponse(f"{redirect}{sep}{urlencode(params)}", status_code=302)
