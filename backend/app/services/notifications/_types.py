"""Shared types of the `notifications` package: pure data only, so providers and
the dispatcher can import from one place without import cycles.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.constants import SecurityStatus
from app.i18n import DEFAULT_LOCALE, Locale


class NotificationProviderId(StrEnum):
    """Stable provider ID, persisted as a string in
    `gitlab_bindings.provider`. A value never changes once introduced
    (contract with the DB)."""

    GOOGLE_CHAT = "google_chat"


class AssetLinkVisibility(StrEnum):
    """Where the link in the notification comes from. The provider can show
    an "organization only / public" label without inspecting the URL
    scheme."""

    ORG = "org"
    PUBLIC = "public"


@dataclass(frozen=True, slots=True)
class AssetLink:
    url: str
    visibility: AssetLinkVisibility


@dataclass(frozen=True, slots=True)
class NotificationContext:
    """Input for `Provider.send()`: a plain DTO with no ORM models (the
    provider stays decoupled from SQLAlchemy)."""

    asset_title: str
    asset_slug: str
    version: int
    commit_sha: str
    file_count: int
    security_status: SecurityStatus | None
    link: AssetLink
    locale: Locale = DEFAULT_LOCALE


@dataclass(frozen=True, slots=True)
class ProviderInfo:
    """Provider metadata serialized by `/api/bindings/providers` for the
    frontend (dropdown and placeholder)."""

    id: NotificationProviderId
    display_name: str
    url_hint: str


class NotificationError(Exception):
    """Base exception of the package; the route maps it to HTTP 400."""


class UnknownProviderError(NotificationError):
    """The provider ID is not registered (e.g. removed from the code while
    existing bindings still hold the old ID in the DB)."""


class InvalidWebhookUrlError(NotificationError):
    """The URL does not match the chosen provider (Google Chat selected, but
    a slack.com URL given)."""
