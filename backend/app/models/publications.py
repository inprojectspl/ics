"""Committed publication results, retained even after the asset is removed."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PublicationReceipt(Base):
    __tablename__ = "publication_receipts"
    __table_args__ = (
        UniqueConstraint(
            "principal_id",
            "project_id",
            "order_id",
            "role",
            "publication_id",
            name="uq_publication_receipt_scope",
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    principal_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # Historical identity, not a live project relation: deleting/moving a project
    # must never change the scope of an already consumed publication key.
    project_id: Mapped[UUID | None]
    order_id: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(100))
    publication_id: Mapped[str] = mapped_column(String(200))
    schema_version: Mapped[int] = mapped_column(Integer)
    payload_hash: Mapped[str] = mapped_column(String(64))
    asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    result: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
