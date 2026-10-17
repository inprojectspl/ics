"""Notifications: user notifications (ADR-0023, `docs/notifications-api.md`)
and binding sync cards to a project webhook, built on the provider pattern
exported here. Modules prefixed with `_` are package-private.
"""

from __future__ import annotations

from ._dispatcher import dispatch_sync_notification
from ._providers._base import NotificationProvider
from ._registry import get_provider, list_provider_infos
from ._types import (
    AssetLink,
    AssetLinkVisibility,
    InvalidWebhookUrlError,
    NotificationContext,
    NotificationError,
    NotificationProviderId,
    ProviderInfo,
    UnknownProviderError,
)


def validate_provider_url(provider_id: str, url: str) -> None:
    """Raise `UnknownProviderError` / `InvalidWebhookUrlError` for an invalid
    pair. Used in the pydantic validation path of the DTO."""
    provider = get_provider(provider_id)
    if not provider.accepts_url(url):
        raise InvalidWebhookUrlError(f"URL does not match provider {provider.display_name}")


__all__ = [
    "AssetLink",
    "AssetLinkVisibility",
    "InvalidWebhookUrlError",
    "NotificationContext",
    "NotificationError",
    "NotificationProvider",
    "NotificationProviderId",
    "ProviderInfo",
    "UnknownProviderError",
    "dispatch_sync_notification",
    "get_provider",
    "list_provider_infos",
    "validate_provider_url",
]
