"""Pydantic DTOs for share endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.constants import SHARE_MODE_REGEX
from app.services.ocr import OcrState


class CreateShareIn(BaseModel):
    mode: str = Field(pattern=SHARE_MODE_REGEX)
    password: str | None = Field(default=None, max_length=512)
    allowed_emails: list[EmailStr] | None = None
    expires_at: datetime | None = None
    max_views: int | None = Field(default=None, ge=1)


class ShareOut(BaseModel):
    id: str
    token: str
    mode: str
    url: str
    expires_at: datetime | None
    max_views: int | None
    view_count: int
    revoked_at: datetime | None
    created_at: datetime
    allowed_emails: list[str] | None
    requires_password: bool


class PasswordChallengeIn(BaseModel):
    password: str = Field(min_length=1, max_length=512)


class ShareResolveIn(BaseModel):
    password: str | None = Field(default=None, max_length=512)
    path: str | None = Field(default=None, max_length=512)
    lines: str | None = Field(default=None, pattern=r"^\d+-\d+$")


class ResolvedShareOut(BaseModel):
    mode: str
    expires_at: datetime | None
    view_count: int
    max_views: int | None


class ResolvedAssetOut(BaseModel):
    id: str
    slug: str
    title: str | None
    kind: str
    version: int
    entry_path: str | None
    size_bytes: int | None
    security_status: str
    created_at: datetime
    updated_at: datetime


class ShareResolveOut(BaseModel):
    """One-shot resolve response for Bearer clients (MCP). `content` is raw
    markdown (not HTML: the agent parses the source anyway, and HTML only
    bloats the LLM context); `tree` for md_collection, `files` for
    html_bundle (metadata only, the bundle renders in the iso-viewer)."""

    share: ResolvedShareOut
    asset: ResolvedAssetOut
    path: str | None
    content: str | None
    total_lines: int | None
    returned_range: list[int] | None
    tree: list[str] | None
    files: list[str] | None
    #: pdf_doc only: OCR of the version whose text is `content` (ADR-0021).
    ocr: OcrState | None = None


class MagicClaimIn(BaseModel):
    m: str = Field(min_length=1, max_length=512)
