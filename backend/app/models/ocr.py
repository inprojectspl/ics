"""OCR runs of document versions (ADR-0021)."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DocumentOcr(Base):
    """The OCR run of one document version: the recognized text belongs to
    the bytes of that version, so a new version starts from no row ("not
    requested"). A retry reuses the row.

    The text itself is stored next to the version (`derived/v{n}/ocr.json`);
    the row holds the state the UI, the agents and the sweeper need."""

    __tablename__ = "document_ocr"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','done','failed')", name="ck_document_ocr_status"
        ),
    )

    asset_id: Mapped[UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(16))
    provider: Mapped[str] = mapped_column(String(32))
    requested_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    requested_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    # Last sign of life of a running job; the sweeper requeues a silent one.
    heartbeat_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Pages of the version without a text layer when the run was queued; kept
    # here so a poll of the state needs no storage read.
    pages_without_text: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Scans with an invisible text layer saved with the file; a run replaces
    # that layer only when `replace_hidden_text` (a request, not an upload).
    pages_with_hidden_text: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    replace_hidden_text: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    # Pages sent to the engine, pages finished, pages where it found text.
    pages_total: Mapped[int | None] = mapped_column(Integer)
    pages_done: Mapped[int | None] = mapped_column(Integer)
    pages_recognized: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(64))
