"""Storage prefixes whose database rows are gone for good (ADR-0029).

A purge or an account deletion records the prefixes in the same commit that
removes the rows, then deletes the files; a row stays until its files are
gone, so a crash or a storage outage cannot orphan them. No foreign keys:
the rows outlive the assets and users they came from."""

from datetime import datetime

from sqlalchemy import BigInteger, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class StorageCleanup(Base):
    __tablename__ = "storage_cleanup"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    prefix: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
