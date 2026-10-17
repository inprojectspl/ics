"""Assets, their versions and per-user pins."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ColumnElement,
    Computed,
    ForeignKey,
    Integer,
    String,
    Text,
    and_,
    func,
    text,
)

# ARRAY from dialects.postgresql: the generic `sqlalchemy.ARRAY` does not
# implement .contains() (the `@>` operator), so the `tags @> ARRAY[...]`
# filter in routes/mcp_assets/index.py needs the dialect-aware type.
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TIMESTAMP, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.constants import AssetKind
from app.db import Base

if TYPE_CHECKING:
    from app.models.sharing import ShareLink


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (
        CheckConstraint(
            "summary_source IN ('human','agent')",
            name="ck_assets_summary_source",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(32), unique=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    kind: Mapped[AssetKind] = mapped_column(String(32))
    title: Mapped[str | None] = mapped_column(String(500))
    storage_prefix: Mapped[str] = mapped_column(Text)
    entry_path: Mapped[str | None] = mapped_column(Text)
    security_status: Mapped[str] = mapped_column(
        String(16), default="clean", server_default="clean"
    )
    security_report: Mapped[dict | None] = mapped_column(JSONB)
    security_bypass: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    security_bypass_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    security_bypass_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    security_bypass_reason: Mapped[str | None] = mapped_column(Text)
    # Extracted text (Markdown, PDF/Office, finished OCR; none for HTML
    # bundles). Deferred so list endpoints do not load every note body.
    search_content: Mapped[str | None] = mapped_column(Text, deferred=True)
    # Shared discovery vector; 0044 creates the accent-insensitive config.
    # Stored generation keeps metadata/content writes and search atomic.
    search_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('public.ics_search', coalesce(title, '')), 'A') || "
            "setweight(to_tsvector('public.ics_search', coalesce(slug, '')), 'A') || "
            "setweight(to_tsvector('public.ics_search', coalesce(summary, '')), 'B') || "
            "setweight(to_tsvector('public.ics_search', "
            "coalesce(ics_immutable_array_to_string(tags, ' '), '')), 'B') || "
            "setweight(to_tsvector('public.ics_search', coalesce(search_content, '')), 'C')",
            persisted=True,
        ),
        deferred=True,
    )
    # SHA-256 of the normalised search_content (lower case, whitespace
    # collapsed) for exact duplicate suggestions; the function is created by
    # migration 0040.
    content_hash: Mapped[str | None] = mapped_column(
        Text, Computed("ics_content_hash(search_content)", persisted=True), deferred=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    # Token size of the default agent read (`services/read_size.py`), set on
    # every content write; NULL for older rows 0041 could not backfill.
    read_tokens: Mapped[int | None] = mapped_column(Integer)
    # MCP-friendly organizational tags (kebab-case slugs, max 20 per asset).
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), server_default="{}", default=list)
    # Cached structural outline (headings/files/wikilinks) rebuilt asynchronously
    # via Arq on each content write. Stale state surfaced via HTTP headers.
    outline_json: Mapped[dict | None] = mapped_column(JSONB)
    outline_version: Mapped[int | None] = mapped_column(Integer)
    outline_status: Mapped[str] = mapped_column(String(16), default="stale", server_default="stale")
    outline_built_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    outline_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    # When and by whom the content last changed (v1 or a new version).
    # `updated_at` also moves on tags, renames, outline and scan writes.
    # Every insert creates content, hence the default.
    content_updated_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), default=lambda: datetime.now(UTC)
    )
    content_updated_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # Document metadata (ADR-0015). Typed columns are the fields system logic
    # depends on; type-specific extras go to `properties`.
    summary: Mapped[str | None] = mapped_column(Text, deferred=True)
    summary_source: Mapped[str | None] = mapped_column(String(8))
    # Content version the summary was written for; older than `version` = stale.
    summary_version: Mapped[int | None] = mapped_column(Integer)
    doc_type: Mapped[str | None] = mapped_column(String(32), ForeignKey("doc_types.key"))
    maintainer_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    review_due_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    reviewed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    language: Mapped[str | None] = mapped_column(String(8))
    properties: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )

    share_links: Mapped[list["ShareLink"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )


class AssetVersion(Base):
    __tablename__ = "asset_versions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    asset_id: Mapped[UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    storage_prefix: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # Author's note on what changed, the equivalent of a commit message.
    change_note: Mapped[str | None] = mapped_column(Text)


class AssetPin(Base):
    """Per-user favourites. Re-pinning bumps `pinned_at`; the extra index on
    `asset_id` serves the CASCADE FK so deleting an asset does not scan pins."""

    __tablename__ = "asset_pins"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    asset_id: Mapped[UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    pinned_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    @classmethod
    def for_user(cls, user_id: UUID) -> ColumnElement[bool]:
        """ON clause for the caller's pins outer join; the composite PK keeps
        it to at most one row per asset."""
        return and_(cls.asset_id == Asset.id, cls.user_id == user_id)
