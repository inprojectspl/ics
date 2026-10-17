"""Request/response DTOs for binding endpoints."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.services import notifications


class CreateBindingIn(BaseModel):
    asset_id: UUID
    gitlab_project_url: str | None = Field(default=None, max_length=500)
    # webhook_url + provider form a pair: both set or both empty.
    # Validated in the route (after pydantic) so the error message can
    # name the provider.
    webhook_url: str | None = Field(default=None, max_length=500)
    provider: notifications.NotificationProviderId | None = None


class PatchBindingIn(BaseModel):
    """Update-in-place. Only fields a binding owner can edit safely:
    the public_key has its own rotate flow, and asset_id is immutable.

    `webhook_url` and `provider` must be patched together (both in the body
    or neither), otherwise 400. Absent from the body means "leave as is"."""

    gitlab_project_url: str | None = Field(default=None, max_length=500)
    webhook_url: str | None = Field(default=None, max_length=500)
    provider: notifications.NotificationProviderId | None = None


class BindingOut(BaseModel):
    id: str
    asset_id: str
    gitlab_project_url: str | None
    webhook_url: str | None
    provider: str | None
    public_key: str
    last_sync_at: str | None
    last_sync_commit_sha: str | None
    created_at: str


class BindingCreateOut(BindingOut):
    """Returned only at creation time; carries the one-shot private key."""

    private_key: str


class ProviderInfoOut(BaseModel):
    id: str
    display_name: str
    url_hint: str


class Manifest(BaseModel):
    binding_id: UUID
    commit_sha: str = Field(min_length=1, max_length=64)
    commit_timestamp: datetime
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
