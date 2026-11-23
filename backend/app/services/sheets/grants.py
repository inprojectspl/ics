"""A person's Google grant for Sheets: connecting, access tokens, disconnecting.

Connecting is its own OAuth flow, bound to the ICS session that started it:
the callback must come back to the same ICS user, and the grant stores the
verified Google `sub`, never a match by e-mail. Signing in with Google is a
different flow and grants nothing here.
"""

from __future__ import annotations

import json
import secrets
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, secret_box
from app.config import Settings
from app.domain_errors import AccessDeniedError, InvalidInputError
from app.models import Asset, GoogleGrant, SheetLink, User
from app.redis_client import get_redis

from . import google

PURPOSE = "google-grant"
STATE_TTL = 600
_STATE = "sheets:connect:"
_TOKEN = "sheets:at:"


def enabled(settings: Settings) -> bool:
    return bool(settings.google_sheets_client_id and settings.google_sheets_client_secret)


async def start(settings: Settings, user: User, back: str) -> str:
    """The Google consent URL; the state remembers who asked and where to return."""
    state = secrets.token_urlsafe(32)
    verifier, challenge = google.pkce_pair()
    await get_redis().setex(
        _STATE + state,
        STATE_TTL,
        json.dumps({"user": str(user.id), "verifier": verifier, "back": back}),
    )
    return google.authorize_url(settings, state=state, challenge=challenge, login_hint=user.email)


async def back_of(state: str) -> str:
    """Where the connection started, to return there whatever the outcome."""
    raw = await get_redis().get(_STATE + state) if state else None
    back = json.loads(raw).get("back") if raw else None
    return (
        back
        if isinstance(back, str) and back.startswith("/") and not back.startswith("//")
        else "/"
    )


async def discard(state: str) -> None:
    """Drop a connection request declined on the consent screen."""
    await get_redis().delete(_STATE + state)


async def finish(
    session: AsyncSession, settings: Settings, user: User, *, state: str, code: str
) -> None:
    """Store the grant of the account that consented."""
    raw = await get_redis().getdel(_STATE + state)
    if raw is None:
        raise InvalidInputError(
            "google_state_invalid", "the connection request expired; start again"
        )
    saved = json.loads(raw)
    if saved["user"] != str(user.id):
        # Started by another ICS session: never attach someone else's Google account.
        raise AccessDeniedError(
            "google_state_mismatch", "the connection was started by another ICS user"
        )
    tokens = await google.exchange_code(settings, code, saved["verifier"])
    scopes = str(tokens.get("scope", "")).split()
    if google.SHEETS_SCOPE not in scopes:
        raise InvalidInputError(
            "google_scope_missing",
            "Google did not grant access to Sheets; allow it on the consent screen",
        )
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise InvalidInputError("google_no_refresh_token", "Google returned no refresh token")
    info = await google.userinfo(tokens["access_token"])
    if not info.get("sub") or not info.get("email_verified"):
        raise InvalidInputError(
            "google_account_unverified", "the Google account has no verified e-mail"
        )

    grant = await session.scalar(
        select(GoogleGrant).where(GoogleGrant.user_id == user.id).with_for_update()
    )
    changed_account = grant is not None and grant.subject != info["sub"]
    if grant is None:
        grant = GoogleGrant(user_id=user.id)
        session.add(grant)
    grant.subject = info["sub"]
    grant.email = str(info.get("email", ""))[:320]
    grant.scopes = " ".join(scopes)
    grant.refresh_token_enc = secret_box.encrypt(settings, PURPOSE, refresh_token)
    if changed_account:
        await _bump_owner_links(session, user.id)
    await audit.record(
        session,
        actor=user,
        action="google_connected",
        payload={"google_email": grant.email, "replaced": changed_account},
    )
    await session.flush()
    await _cache_token(grant.id, settings, tokens)


async def disconnect(session: AsyncSession, settings: Settings, user: User) -> bool:
    grant = await session.scalar(
        select(GoogleGrant).where(GoogleGrant.user_id == user.id).with_for_update()
    )
    if grant is None:
        return False
    token = secret_box.decrypt(settings, PURPOSE, grant.refresh_token_enc)
    await get_redis().delete(_TOKEN + str(grant.id))
    await _bump_owner_links(session, user.id)
    await session.delete(grant)
    await audit.record(
        session, actor=user, action="google_disconnected", payload={"google_email": grant.email}
    )
    await session.commit()
    if token:
        try:
            await google.revoke(token)
        except google.GoogleError:
            pass  # Removed here either way; Google drops unused grants on its own.
    return True


async def _bump_owner_links(session: AsyncSession, user_id: UUID) -> None:
    """Links that write with this person's account as the owner's: a preview
    made with the previous account must not be applied with another."""
    owned = select(Asset.id).where(Asset.owner_id == user_id)
    await session.execute(
        update(SheetLink)
        .where(SheetLink.account_mode == "owner_account", SheetLink.asset_id.in_(owned))
        .values(revision=SheetLink.revision + 1)
    )


async def grant_of(session: AsyncSession, user_id: UUID) -> GoogleGrant | None:
    grant: GoogleGrant | None = await session.scalar(
        select(GoogleGrant).where(GoogleGrant.user_id == user_id)
    )
    return grant


async def _cache_token(grant_id: UUID, settings: Settings, tokens: dict[str, Any]) -> None:
    ttl = int(tokens.get("expires_in", 3600)) - 120
    if ttl > 0:
        await get_redis().setex(
            _TOKEN + str(grant_id),
            ttl,
            secret_box.encrypt(settings, PURPOSE + ":access", tokens["access_token"]),
        )


async def access_token(session: AsyncSession, settings: Settings, user_id: UUID) -> str:
    """A live access token of `user_id`'s grant. Raises GoogleError
    `google_not_connected` when there is none."""
    grant = await grant_of(session, user_id)
    if grant is None:
        raise google.GoogleError("google_not_connected", "no Google account is connected")
    cached = await get_redis().get(_TOKEN + str(grant.id))
    if cached is not None:
        if token := secret_box.decrypt(settings, PURPOSE + ":access", cached):
            return token
    refresh_token = secret_box.decrypt(settings, PURPOSE, grant.refresh_token_enc)
    if refresh_token is None:
        raise google.GoogleError("google_grant_invalid", "the stored Google grant cannot be read")
    tokens = await google.refresh(settings, refresh_token)
    await _cache_token(grant.id, settings, tokens)
    return str(tokens["access_token"])
