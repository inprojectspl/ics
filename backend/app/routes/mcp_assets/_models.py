"""Pydantic response/request models shared across MCP endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.services.ocr import OcrState

from ._shared import _HTML_BUNDLE_MAX_FILES, _MAX_TAGS, _TAG_RE


class MaintainerOut(BaseModel):
    id: UUID
    email: str | None
    display_name: str | None


class SupersededByOut(BaseModel):
    id: UUID
    slug: str
    title: str | None


class AssetIndexItem(BaseModel):
    id: UUID
    slug: str
    title: str | None
    kind: str
    size_bytes: int | None
    version: int
    updated_at: datetime
    content_updated_at: datetime | None
    content_updated_by: UUID | None
    pinned: bool
    owner_id: UUID
    project_id: UUID | None
    tags: list[str]
    has_versions: bool
    access_role: Literal["owner_file", "project_owner", "editor", "viewer"]
    # With a project filter: the asset's home is another project (ADR-0017).
    shared_in: bool = False
    # Document metadata (ADR-0015); lists carry a summary preview.
    summary: str | None = None
    summary_source: Literal["human", "agent"] | None = None
    doc_type: str | None = None
    freshness: Literal["superseded", "review_overdue", "current"] = "current"
    # The visible successor when `freshness` is `superseded` (ADR-0015).
    superseded_by: SupersededByOut | None = None
    # Slug of the newest visible document of the `supersedes` chain (the end
    # of v1 -> v2 -> v3 for v1 and v2); set together with `superseded_by`.
    latest: str | None = None
    # Tokens of the default read (`services/read_size.py`): for a collection
    # the entry file, for PDF/Office the Markdown, for HTML the entry page.
    estimated_tokens: int | None = None
    flags: list[Literal["summary_stale", "basis_changed"]] = Field(default_factory=list)
    maintainer: MaintainerOut | None = None


class AssetMetaItem(AssetIndexItem):
    """`/by-slug/{slug}/meta`: the index row plus the fields of the metadata
    writes (`asset_projection.detail_fields`), which lists leave out."""

    summary_version: int | None = None
    maintainer_id: UUID | None = None
    review_due_at: datetime | None = None
    reviewed_at: datetime | None = None
    reviewed_by: UUID | None = None
    language: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    #: pdf_doc only: OCR of the current version; null for other kinds.
    ocr: OcrState | None = None


class AssetIndexPage(BaseModel):
    items: list[AssetIndexItem]
    next_cursor: str | None


def normalize_tags(v: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for tag in v:
        tag = tag.lower().strip()
        if not _TAG_RE.match(tag):
            raise ValueError(f"tag invalid: {tag!r}")
        if tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
    if len(out) > _MAX_TAGS:
        raise ValueError(f"max {_MAX_TAGS} tags per asset")
    return out


class TagsUpdate(BaseModel):
    tags: list[str] = Field(default_factory=list, max_length=_MAX_TAGS)

    @field_validator("tags")
    @classmethod
    def _validate_tags(cls, v: list[str]) -> list[str]:
        return normalize_tags(v)


class HtmlBundleFile(BaseModel):
    path: str
    content_text: str | None = None
    content_base64: str | None = None
    mime: str | None = None

    @field_validator("path")
    @classmethod
    def _check_path(cls, v: str) -> str:
        if v.startswith("/") or ".." in v.split("/"):
            raise ValueError("path: leading / or .. not allowed")
        return v


class HtmlBundleCreate(BaseModel):
    title: str
    entry_path: str
    # None (ics-mcp sends an explicit null) means the multipart default, org_sso.
    share_mode: Literal["org_sso", "public"] | None = None
    project_id: UUID | None = None
    tags: list[str] = Field(default_factory=list, max_length=_MAX_TAGS)
    doc_type: str | None = Field(default=None, max_length=32)
    summary: str | None = None
    files: list[HtmlBundleFile] = Field(..., min_length=1, max_length=_HTML_BUNDLE_MAX_FILES)

    @field_validator("tags")
    @classmethod
    def _validate_tags(cls, v: list[str]) -> list[str]:
        return normalize_tags(v)


class SearchSnippet(BaseModel):
    # `path` and 1-based `line` of the snippet in the file; md_single only.
    path: str | None
    line: int | None
    text: str
    # 1-based page of the snippet; pdf_doc only.
    page: int | None = None


class SearchHit(BaseModel):
    id: UUID
    slug: str
    title: str | None
    kind: str
    score: float
    # Summary preview, doc type and freshness for the viewer, so a hit can
    # be skipped (superseded, wrong type) without a meta call.
    summary: str | None = None
    doc_type: str | None = None
    freshness: Literal["superseded", "review_overdue", "current"] = "current"
    # Slug of the newest visible document of the `supersedes` chain, when
    # the hit is superseded; token size of its default read.
    latest: str | None = None
    estimated_tokens: int | None = None
    snippets: list[SearchSnippet]


class SearchPage(BaseModel):
    items: list[SearchHit]
    total: int
    offset: int
    limit: int
    has_more: bool
