"""Organisation-wide document type vocabulary (ADR-0015)."""

from datetime import datetime

from sqlalchemy import Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DocType(Base):
    """A document type. Labels are data edited by admins at runtime, not i18n
    catalogue keys; `archived_at` retires a type without deleting it."""

    __tablename__ = "doc_types"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    label_pl: Mapped[str] = mapped_column(String(100))
    label_en: Mapped[str] = mapped_column(String(100))
    agent_hint: Mapped[str | None] = mapped_column(Text)
    default_review_days: Mapped[int | None] = mapped_column(Integer)
    properties_schema: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    archived_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
