"""Notification preferences: defaults, the API shape and the Chat webhook.

A user without a row gets the defaults below; the row is created on the
first change.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal, get_args
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app import secret_box
from app.config import Settings
from app.domain_errors import InvalidInputError
from app.models import NotificationPreference

from ._providers.google_chat import GoogleChatProvider
from .items import EVENT_KINDS, EventKind

# In-app delivery is always on while notifications are enabled, so it is not
# a stored choice; these are the channels a user picks per event.
ChannelId = Literal["push", "email", "chat"]
CHANNELS: tuple[ChannelId, ...] = get_args(ChannelId)
EmailMode = Literal["off", "batched", "daily"]
_EMAIL_MODES: Final[dict[str, EmailMode]] = {m: m for m in get_args(EmailMode)}

_CHAT_PURPOSE: Final[str] = "ics-notification-chat-webhook"
_ALL: Final[list[ChannelId]] = list(CHANNELS)
DEFAULT_EVENTS: Final[dict[EventKind, list[ChannelId]]] = {
    "asset.created": _ALL,
    "asset.added": _ALL,
    "asset.updated": _ALL,
    "asset.deleted": ["push"],
}


@dataclass(frozen=True, slots=True)
class Prefs:
    """Effective preferences of one user (defaults applied)."""

    enabled: bool
    watch_own_assets: bool
    email_mode: EmailMode
    events: dict[EventKind, list[ChannelId]]
    chat_enabled: bool
    chat_configured: bool
    chat_space: str | None
    chat_error_code: str | None

    def wants(self, kind: EventKind, channel: ChannelId) -> bool:
        if not self.enabled:
            return False
        if channel == "email" and self.email_mode == "off":
            return False
        if channel == "chat" and not (self.chat_enabled and self.chat_configured):
            return False
        return channel in self.events.get(kind, [])


DEFAULT_PREFS: Final[Prefs] = Prefs(
    enabled=True,
    watch_own_assets=True,
    email_mode="off",
    events=dict(DEFAULT_EVENTS),
    chat_enabled=False,
    chat_configured=False,
    chat_space=None,
    chat_error_code=None,
)


def normalize_events(raw: dict[str, Any] | None) -> dict[EventKind, list[ChannelId]]:
    """Stored JSON over the defaults; unknown kinds and channels are dropped,
    so a removed channel in the code never breaks an old row."""
    out: dict[EventKind, list[ChannelId]] = {k: list(v) for k, v in DEFAULT_EVENTS.items()}
    for kind in EVENT_KINDS:
        value = (raw or {}).get(kind)
        if isinstance(value, list):
            out[kind] = [c for c in CHANNELS if c in value]
    return out


def from_row(row: NotificationPreference | None) -> Prefs:
    if row is None:
        return DEFAULT_PREFS
    mode = _EMAIL_MODES.get(row.email_mode, "off")
    return Prefs(
        enabled=row.enabled,
        watch_own_assets=row.watch_own_assets,
        email_mode=mode,
        events=normalize_events(row.events),
        chat_enabled=row.chat_enabled,
        chat_configured=row.chat_webhook_enc is not None,
        chat_space=row.chat_space,
        chat_error_code=row.chat_error_code,
    )


async def load(session: AsyncSession, user_id: UUID) -> Prefs:
    return from_row(await session.get(NotificationPreference, user_id))


async def get_or_create_row(session: AsyncSession, user_id: UUID) -> NotificationPreference:
    row = await session.get(NotificationPreference, user_id)
    if row is None:
        # Column defaults are the ones of `DEFAULT_PREFS`.
        row = NotificationPreference(user_id=user_id, events={})
        session.add(row)
        await session.flush()
    return row


def chat_space_of(url: str) -> str | None:
    """`spaces/AAAA` from a webhook URL: enough for the user to recognise it,
    useless for posting (the key and token stay secret)."""
    parts = urlparse(url).path.split("/")
    if "spaces" in parts:
        idx = parts.index("spaces")
        if idx + 1 < len(parts) and parts[idx + 1]:
            return parts[idx + 1][:64]
    return None


def set_chat_webhook(row: NotificationPreference, url: str | None, settings: Settings) -> None:
    """Store (encrypted) or clear the webhook. Only a Google Chat incoming
    webhook is accepted, whoever calls this."""
    if url is not None and not GoogleChatProvider().accepts_url(url):
        raise InvalidInputError(
            "invalid_webhook_url", "expected a Google Chat incoming webhook URL"
        )
    if url is None:
        row.chat_webhook_enc = None
        row.chat_space = None
        row.chat_enabled = False
    else:
        row.chat_webhook_enc = secret_box.encrypt(settings, _CHAT_PURPOSE, url)
        row.chat_space = chat_space_of(url)
        row.chat_enabled = True
    row.chat_error_code = None


def chat_webhook(row: NotificationPreference, settings: Settings) -> str | None:
    if row.chat_webhook_enc is None:
        return None
    return secret_box.decrypt(settings, _CHAT_PURPOSE, row.chat_webhook_enc)
