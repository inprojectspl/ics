"""Public host names of micro-application environments."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.slug import _ALPHABET

# The readable alphabet of `app.slug`; the database refuses anything else.
HOST_NAME_CHECK = f"name ~ '^[{_ALPHABET}]{{8}}$'"


class MicroAppHostName(Base):
    """Permanent reservation of the short public host name of one app
    environment (`<name>.<app_host_suffix>`). Rows are never deleted and have
    no foreign key to the asset, so a name is not handed to another app even
    after its asset is purged."""

    __tablename__ = "microapp_host_names"
    __table_args__ = (
        UniqueConstraint("asset_id", "environment", name="uq_microapp_host_name_asset_env"),
        CheckConstraint(HOST_NAME_CHECK, name="ck_microapp_host_name_format"),
    )

    name: Mapped[str] = mapped_column(String(8), primary_key=True)
    asset_id: Mapped[UUID] = mapped_column()
    environment: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
