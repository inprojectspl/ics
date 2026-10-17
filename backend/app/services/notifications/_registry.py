"""Provider lookup: the single access point by stable ID."""

from __future__ import annotations

from typing import Final

from ._providers import NotificationProvider, all_providers
from ._types import (
    NotificationProviderId,
    ProviderInfo,
    UnknownProviderError,
)

_BY_ID: Final[dict[NotificationProviderId, NotificationProvider]] = {
    p.id: p for p in all_providers()
}


def get_provider(provider_id: NotificationProviderId | str) -> NotificationProvider:
    """Return the provider for an ID. The `str` to enum conversion happens
    here, so callers can pass raw strings from the DB / DTO."""
    try:
        # KeyError: an enum value added without an instance in the registry.
        return _BY_ID[NotificationProviderId(provider_id)]
    except (ValueError, KeyError) as e:
        raise UnknownProviderError(f"unknown provider: {provider_id!r}") from e


def list_provider_infos() -> list[ProviderInfo]:
    """Sorted provider metadata for the frontend dropdown."""
    return [
        ProviderInfo(id=p.id, display_name=p.display_name, url_hint=p.url_hint)
        for p in sorted(all_providers(), key=lambda p: p.display_name)
    ]
