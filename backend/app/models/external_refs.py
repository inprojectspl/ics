"""Links from assets and projects to external systems (ADR-0018)."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Text, false, func
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._helpers import sql_in_list

# The CHECK constraints mirror these sets.
EXTERNAL_SYSTEMS: tuple[str, ...] = ("openproject", "project_standard", "gitlab", "url")
EXTERNAL_ENTITIES: tuple[str, ...] = (
    "work_package",
    "project",
    "version",
    "node",
    "merge_request",
    "page",
)
EXTERNAL_ROLES: tuple[str, ...] = ("context", "deliverable", "reference")
EXTERNAL_ORIGINS: tuple[str, ...] = ("manual", "agent", "integration")
PROJECT_EXTERNAL_SYSTEMS: tuple[str, ...] = ("openproject", "project_standard")


class AssetExternalRef(Base):
    __tablename__ = "asset_external_refs"
    __table_args__ = (
        CheckConstraint(
            f"system IN ({sql_in_list(EXTERNAL_SYSTEMS)})", name="ck_asset_external_refs_system"
        ),
        CheckConstraint(
            f"entity IN ({sql_in_list(EXTERNAL_ENTITIES)})", name="ck_asset_external_refs_entity"
        ),
        CheckConstraint(
            f"role IN ({sql_in_list(EXTERNAL_ROLES)})", name="ck_asset_external_refs_role"
        ),
        CheckConstraint(
            f"origin IN ({sql_in_list(EXTERNAL_ORIGINS)})", name="ck_asset_external_refs_origin"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    asset_id: Mapped[UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    system: Mapped[str] = mapped_column(String(32))
    entity: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(Text)
    external_scope: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(16))
    required: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    label: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    asset_path: Mapped[str | None] = mapped_column(Text)
    pinned_version: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(String(16))
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )


class ProjectExternalRef(Base):
    """Maps an ICS project to an external project; one home per external id."""

    __tablename__ = "project_external_refs"
    __table_args__ = (
        CheckConstraint(
            f"system IN ({sql_in_list(PROJECT_EXTERNAL_SYSTEMS)})",
            name="ck_project_external_refs_system",
        ),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    system: Mapped[str] = mapped_column(String(32), primary_key=True)
    external_id: Mapped[str] = mapped_column(Text, primary_key=True)
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )


class ProjectKeyDocument(Base):
    __tablename__ = "project_key_documents"

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    asset_id: Mapped[UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)
