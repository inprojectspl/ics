"""E-mail and Google Chat batches, sent by the sweeper when they are due.

Entries the user already read or deleted in the app are dropped: nobody
needs an e-mail about what they have seen.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Final
from urllib.parse import quote
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import tokens
from app.config import Settings
from app.email_outbox import queue_email
from app.email_templates_notify import notification_digest
from app.i18n import resolve_locale
from app.models import NotificationPreference, User
from app.services.sharing import build_app_url

from . import inbox, preferences, schedule
from .channels import chat
from .fanout import deliver
from .items import build_payload
from .recipients import Recipient
from .render import Rendered, render

logger = logging.getLogger("ics.notifications.batches")

_CHAT_RETRY_SECONDS: Final[int] = 300
_CHAT_MAX_ATTEMPTS: Final[int] = 5


def unsubscribe_token(user_id: UUID) -> str:
    return tokens.issue("notify_unsubscribe", str(user_id))


async def _unread_entries(redis: Redis, uid: UUID, ids: list[str]) -> list[inbox.Entry]:
    entries = await inbox.get_many(redis, uid, ids)
    # Newest first, like the inbox.
    return sorted((e for e in entries if not e.read), key=lambda e: e.id, reverse=True)


async def _user_and_prefs(
    session: AsyncSession, uid: UUID
) -> tuple[User | None, NotificationPreference | None]:
    row = (
        await session.execute(
            select(User, NotificationPreference)
            .outerjoin(NotificationPreference, NotificationPreference.user_id == User.id)
            .where(User.id == uid)
        )
    ).first()
    return (row[0], row[1]) if row else (None, None)


@dataclass(frozen=True, slots=True)
class _Batch:
    user: User
    row: NotificationPreference | None
    prefs: preferences.Prefs
    items: list[Rendered]
    ids: list[str]


async def _open_batch(
    session: AsyncSession,
    redis: Redis,
    settings: Settings,
    uid_str: str,
    queue: schedule.BatchQueue,
) -> _Batch | None:
    """Take a due batch and render what is still unread; None when nothing
    is left to send."""
    ids = await schedule.take_batch(redis, uid_str, queue)
    uid = UUID(uid_str)
    user, row = await _user_and_prefs(session, uid)
    prefs = preferences.from_row(row)
    if user is None or not ids or not prefs.enabled:
        return None
    entries = await _unread_entries(redis, uid, ids)
    if not entries:
        return None
    locale = resolve_locale(user.locale)
    return _Batch(
        user=user,
        row=row,
        prefs=prefs,
        items=[render(e.id, e.payload, locale, settings) for e in entries],
        ids=[e.id for e in entries],
    )


async def send_mail(session: AsyncSession, redis: Redis, settings: Settings, uid_str: str) -> int:
    batch = await _open_batch(session, redis, settings, uid_str, "mail")
    if batch is None or batch.prefs.email_mode == "off":
        return 0
    token = quote(unsubscribe_token(batch.user.id))
    subject, text, html = notification_digest(
        items=batch.items,
        inbox_url=build_app_url(settings, "/notifications"),
        settings_url=build_app_url(settings, "/account/notifications"),
        unsubscribe_url=build_app_url(settings, f"/notifications/unsubscribe?token={token}"),
        daily=batch.prefs.email_mode == "daily",
        locale=resolve_locale(batch.user.locale),
    )
    await queue_email(
        session,
        to_email=batch.user.email,
        subject=subject,
        body=text,
        body_html=html,
        purpose="notification",
        settings=settings,
        list_unsubscribe_url=build_app_url(
            settings, f"/api/notifications/unsubscribe?token={token}"
        ),
    )
    await session.commit()
    return len(batch.items)


async def send_chat(session: AsyncSession, redis: Redis, settings: Settings, uid_str: str) -> int:
    batch = await _open_batch(session, redis, settings, uid_str, "chat")
    if batch is None or batch.row is None or not batch.prefs.chat_enabled:
        return 0
    url = preferences.chat_webhook(batch.row, settings)
    if url is None:
        return 0
    result = await chat.post(url, chat.build_card(batch.items, resolve_locale(batch.user.locale)))
    if result == "ok":
        await schedule.reset_attempts(redis, uid_str, "chat")
        return len(batch.items)
    if (
        result == "retry"
        and await schedule.bump_attempts(redis, uid_str, "chat") < _CHAT_MAX_ATTEMPTS
    ):
        await schedule.return_batch(
            redis, uid_str, "chat", batch.ids, time.time() + _CHAT_RETRY_SECONDS
        )
        return 0
    code = "rejected" if result == "disable" else "unreachable"
    await disable_chat(session, redis, settings, batch.user, batch.row, code)
    return 0


async def disable_chat(
    session: AsyncSession,
    redis: Redis,
    settings: Settings,
    user: User,
    row: NotificationPreference,
    error_code: str,
) -> None:
    """Stop posting to a dead webhook and tell the user in the app."""
    row.chat_enabled = False
    row.chat_error_code = error_code
    await session.commit()
    await schedule.reset_attempts(redis, str(user.id), "chat")
    payload = build_payload(
        "channel.chat_disabled",
        asset=None,
        project=None,
        actor_id=None,
        actor_name=None,
        params={"error_code": error_code},
    )
    recipient = Recipient(id=user.id, locale=user.locale, prefs=preferences.from_row(row))
    await deliver(redis, settings, [(recipient, payload)])
    logger.info("notify.channel.failed channel=chat user=%s code=%s", user.id, error_code)
