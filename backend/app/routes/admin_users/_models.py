"""Pydantic DTOs for admin user-management."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class InviteIn(BaseModel):
    email: EmailStr
    display_name: str | None = Field(default=None, max_length=255)
    role: Literal["user", "external", "admin"] = "user"


class PatchUserIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=255)
    role: Literal["user", "external", "admin"] | None = None
    storage_quota_bytes: int | None = Field(default=None, ge=0, le=10 * 1024**4)
    # 1 GiB is a sanity bound on admin input; the real ceiling is the global
    # `settings.max_asset_bytes` (100 MiB), which applies independently.
    bundle_max_bytes: int | None = Field(default=None, ge=0, le=1024**3)
    html_autobypass: bool | None = None


class LockIn(BaseModel):
    minutes: int = Field(default=15, ge=1, le=60 * 24 * 30)
    reason: str | None = Field(default=None, max_length=500)
