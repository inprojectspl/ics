"""Typed edges between assets (ADR-0016)."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._helpers import sql_in_list

# Order matters only for display; the CHECK constraint mirrors this set.
RELATION_TYPES: tuple[str, ...] = (
    "derived_from",
    "supersedes",
    "depends_on",
    "part_of",
    "references",
    "relates_to",
    "duplicates",
    "contradicts",
)
RELATION_ORIGINS: tuple[str, ...] = ("manual", "agent", "extracted", "integration")


class AssetRelation(Base):
    __tablename__ = "asset_relations"
    __table_args__ = (
        CheckConstraint(
            f"relation_type IN ({sql_in_list(RELATION_TYPES)})",
            name="ck_asset_relations_type",
        ),
        CheckConstraint(
            f"origin IN ({sql_in_list(RELATION_ORIGINS)})",
            name="ck_asset_relations_origin",
        ),
        CheckConstraint(
            "source_asset_id <> target_asset_id",
            name="ck_asset_relations_not_self",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_asset_id: Mapped[UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    target_asset_id: Mapped[UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    relation_type: Mapped[str] = mapped_column(String(32))
    source_path: Mapped[str | None] = mapped_column(Text)
    target_path: Mapped[str | None] = mapped_column(Text)
    target_anchor: Mapped[str | None] = mapped_column(Text)
    target_version: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(String(500))
    origin: Mapped[str] = mapped_column(String(16))
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )


class DuplicateDismissal(Base):
    """A pair of assets a person marked "not a duplicate", so the hygiene
    suggestions stop proposing it. One row per unordered pair (a < b)."""

    __tablename__ = "duplicate_dismissals"
    __table_args__ = (
        CheckConstraint("asset_a_id < asset_b_id", name="ck_duplicate_dismissals_order"),
    )

    asset_a_id: Mapped[UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True
    )
    asset_b_id: Mapped[UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True
    )
    dismissed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
