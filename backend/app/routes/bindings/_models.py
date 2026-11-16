"""Request/response DTOs for binding endpoints."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

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
    release_id: str | None = Field(
        default=None, min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
    )
    release_generation: int | None = Field(default=None, strict=True, ge=1, le=2**63 - 1)

    @model_validator(mode="after")
    def release_identity_is_complete(self) -> Manifest:
        if (self.release_id is None) != (self.release_generation is None):
            raise ValueError("release_id and release_generation must be supplied together")
        return self
