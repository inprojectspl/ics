"""Notification configuration (ADR-0023): watches, preferences, push devices.

The notifications themselves are in Redis (`services/notifications/inbox.py`);
these tables hold only what must survive a Redis flush.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Watch(Base):
    """A user watching one asset or one project. Two nullable foreign keys
    rather than a polymorphic target, so cascades keep the table clean."""

    __tablename__ = "watches"
    __table_args__ = (
        CheckConstraint("num_nonnulls(asset_id, project_id) = 1", name="ck_watches_one_target"),
        CheckConstraint(
            "(asset_id IS NOT NULL AND level IN ('watch','mute'))"
            " OR (project_id IS NOT NULL AND level IN ('new','all'))",
            name="ck_watches_level",
        ),
        Index(
            "uq_watches_user_asset",
            "user_id",
            "asset_id",
            unique=True,
            postgresql_where=text("asset_id IS NOT NULL"),
        ),
        Index(
            "uq_watches_user_project",
            "user_id",
            "project_id",
            unique=True,
            postgresql_where=text("project_id IS NOT NULL"),
        ),
        # The partial unique indexes above do not serve `user_id = ?` alone.
        Index("ix_watches_user_created", "user_id", "created_at"),
        Index("ix_watches_asset", "asset_id", postgresql_where=text("asset_id IS NOT NULL")),
        Index("ix_watches_project", "project_id", postgresql_where=text("project_id IS NOT NULL")),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    asset_id: Mapped[UUID | None] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    level: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )


class NotificationPreference(Base):
    """One row per user; a missing row means the defaults of
    `services/notifications/preferences.py`."""

    __tablename__ = "notification_preferences"
    __table_args__ = (
        CheckConstraint(
            "email_mode IN ('off','batched','daily')", name="ck_notification_prefs_email_mode"
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    watch_own_assets: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    email_mode: Mapped[str] = mapped_column(String(8), default="off", server_default="off")
    # Channels per event kind: {"asset.updated": ["app", "push"], ...}.
    events: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    # Fernet token (`app/secret_box.py`): the webhook URL is a bearer secret.
    chat_webhook_enc: Mapped[str | None] = mapped_column(Text)
    chat_space: Mapped[str | None] = mapped_column(String(64))
    chat_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    chat_error_code: Mapped[str | None] = mapped_column(String(32))
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PushSubscription(Base):
    """A browser (device) registered for Web Push."""

    __tablename__ = "push_subscriptions"
    __table_args__ = (Index("ix_push_subscriptions_user", "user_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(String(128))
    auth: Mapped[str] = mapped_column(String(64))
    label: Mapped[str | None] = mapped_column(String(120))
    failures: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    last_success_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
