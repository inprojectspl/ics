"""Notification preferences, push devices, e-mail opt-out and watched items."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import ratelimit, tokens
from app.auth import CurrentUser
from app.config import Settings, get_settings
from app.db import get_session
from app.errors import ApiError
from app.i18n import resolve_locale
from app.models import NotificationPreference, PushSubscription, User
from app.redis_client import get_redis
from app.services.notifications import preferences, watches
from app.services.notifications.channels import chat, vapid, webpush
from app.services.notifications.items import EventKind
from app.services.notifications.preferences import ChannelId, EmailMode, Prefs
from app.util import ip_hash

from ._router import router, watches_router


class PreferencesIn(BaseModel):
    enabled: bool | None = None
    watch_own_assets: bool | None = None
    email_mode: EmailMode | None = None
    events: dict[EventKind, list[ChannelId]] | None = None
    chat_webhook_url: str | None = Field(default=None, max_length=1000)
    chat_enabled: bool | None = None


class PushKeysIn(BaseModel):
    p256dh: str = Field(min_length=16, max_length=128)
    auth: str = Field(min_length=8, max_length=64)


class PushSubscriptionIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=2000)
    keys: PushKeysIn
    label: str | None = Field(default=None, max_length=120)


class PushEndpointIn(BaseModel):
    endpoint: str = Field(max_length=2000)


class UnsubscribeIn(BaseModel):
    token: str = Field(max_length=500)


def _out(p: Prefs, settings: Settings) -> dict[str, Any]:
    push_ready = webpush.is_configured(settings)
    return {
        "enabled": p.enabled,
        "watch_own_assets": p.watch_own_assets,
        "email_mode": p.email_mode,
        "events": p.events,
        "chat": {
            "configured": p.chat_configured,
            "space": p.chat_space,
            "enabled": p.chat_enabled,
            "error_code": p.chat_error_code,
        },
        "push": {
            "available": push_ready,
            "public_key": vapid.public_key(settings.vapid_private_key) if push_ready else None,
        },
        "email_available": bool(settings.smtp_host),
    }


@router.get("/preferences")
async def get_preferences(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    return _out(await preferences.load(session, user.id), settings)


@router.put("/preferences")
async def put_preferences(
    body: PreferencesIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    row = await preferences.get_or_create_row(session, user.id)
    if body.enabled is not None:
        row.enabled = body.enabled
    if body.watch_own_assets is not None:
        row.watch_own_assets = body.watch_own_assets
    if body.email_mode is not None:
        row.email_mode = body.email_mode
    if body.events is not None:
        row.events = {**(row.events or {}), **{k: list(v) for k, v in body.events.items()}}
    if "chat_webhook_url" in body.model_fields_set:
        url = (body.chat_webhook_url or "").strip() or None
        preferences.set_chat_webhook(row, url, settings)
    if body.chat_enabled is not None:
        if body.chat_enabled and row.chat_webhook_enc is None:
            raise ApiError(
                status.HTTP_400_BAD_REQUEST, "chat_not_configured", "no Google Chat webhook set"
            )
        row.chat_enabled = body.chat_enabled
        if body.chat_enabled:
            row.chat_error_code = None
    await session.commit()
    return _out(preferences.from_row(row), settings)


@router.post("/chat/test", status_code=status.HTTP_204_NO_CONTENT)
async def test_chat(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    await ratelimit.enforce(get_redis(), ratelimit.NOTIFY_CHAT_TEST, str(user.id))
    row = await session.get(NotificationPreference, user.id)
    url = preferences.chat_webhook(row, settings) if row is not None else None
    if url is None:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, "chat_not_configured", "no Google Chat webhook set"
        )
    result = await chat.post(url, chat.sample_card(resolve_locale(user.locale)))
    if result != "ok":
        raise ApiError(
            status.HTTP_502_BAD_GATEWAY,
            "chat_delivery_failed",
            "Google Chat did not accept the message",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/push/subscriptions")
async def list_push_subscriptions(
    user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> dict[str, Any]:
    rows = await session.scalars(
        select(PushSubscription)
        .where(PushSubscription.user_id == user.id)
        .order_by(PushSubscription.created_at.desc())
    )
    return {
        "items": [
            {
                "id": str(r.id),
                "label": r.label,
                "created_at": r.created_at.isoformat(),
                "last_success_at": r.last_success_at.isoformat() if r.last_success_at else None,
            }
            for r in rows
        ]
    }


@router.put("/push/subscriptions")
async def put_push_subscription(
    body: PushSubscriptionIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, str]:
    if not webpush.is_configured(settings):
        raise ApiError(status.HTTP_409_CONFLICT, "push_not_configured", "web push is not set up")
    if not webpush.endpoint_allowed(body.endpoint):
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, "push_endpoint_not_allowed", "unknown push service"
        )
    row = await session.scalar(
        select(PushSubscription).where(PushSubscription.endpoint == body.endpoint)
    )
    if row is None:
        row = PushSubscription(endpoint=body.endpoint, user_id=user.id, p256dh="", auth="")
        session.add(row)
    # A browser profile that signs in as someone else takes the device over.
    row.user_id = user.id
    row.p256dh = body.keys.p256dh
    row.auth = body.keys.auth
    row.label = body.label
    row.failures = 0
    await session.commit()
    return {"id": str(row.id)}


@router.post("/push/unsubscribe", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe_push_endpoint(
    body: PushEndpointIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    await session.execute(
        delete(PushSubscription).where(
            PushSubscription.user_id == user.id, PushSubscription.endpoint == body.endpoint
        )
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/push/subscriptions/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_push_subscription(
    subscription_id: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    result = await session.execute(
        delete(PushSubscription)
        .where(
            PushSubscription.user_id == user.id, PushSubscription.id == _device_id(subscription_id)
        )
        .returning(PushSubscription.id)
    )
    if result.first() is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "push_subscription_not_found", "device not found")
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _device_id(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as e:
        raise ApiError(
            status.HTTP_404_NOT_FOUND, "push_subscription_not_found", "device not found"
        ) from e


@router.post("/unsubscribe", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe_email(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    token: Annotated[str | None, Query(max_length=500)] = None,
) -> Response:
    """One-click opt-out (RFC 8058): mail clients POST the `List-Unsubscribe`
    URL (token in the query, form body `List-Unsubscribe=One-Click`); the
    landing page posts JSON `{token}`. No login needed."""
    await ratelimit.enforce(get_redis(), ratelimit.NOTIFY_UNSUBSCRIBE, ip_hash(request))
    if token is None and request.headers.get("content-type", "").startswith("application/json"):
        token = UnsubscribeIn.model_validate(await request.json()).token
    try:
        user = await session.get(User, UUID(tokens.verify("notify_unsubscribe", token or "")))
    except (tokens.TokenInvalid, ValueError):
        user = None
    if user is None:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, "invalid_unsubscribe_token", "invalid or expired link"
        )
    row = await preferences.get_or_create_row(session, user.id)
    row.email_mode = "off"
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@watches_router.get("")
async def list_watches(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> dict[str, Any]:
    items, total = await watches.list_for_user(
        session, user.id, limit=page_size, offset=(page - 1) * page_size
    )
    return {"items": items, "total": total}
