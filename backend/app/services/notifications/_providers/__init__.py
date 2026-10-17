"""Provider registry: one instance per provider module in `_INSTANCES`."""

from __future__ import annotations

from typing import Final

from ._base import NotificationProvider
from .google_chat import GoogleChatProvider

_INSTANCES: Final[tuple[NotificationProvider, ...]] = (GoogleChatProvider(),)


def all_providers() -> tuple[NotificationProvider, ...]:
    return _INSTANCES


__all__ = ["NotificationProvider", "all_providers"]
