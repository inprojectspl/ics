"""External integrations: GitLab sync bindings and the CDN allowlist."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class GitLabBinding(Base):
    __tablename__ = "gitlab_bindings"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    asset_id: Mapped[UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    gitlab_project_url: Mapped[str | None] = mapped_column(Text)
    public_key: Mapped[str] = mapped_column(Text)
    # Wallclock when our server recorded the last successful sync.
    last_sync_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    last_sync_commit_sha: Mapped[str | None] = mapped_column(String(64))
    # Commit timestamp from the manifest, used as a monotonic anchor for
    # replay protection (incoming sync must be > stored value). Not the
    # same as last_sync_at: clock skew on the CI side is normal.
    last_sync_timestamp: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    # Outbound notification: the (provider, webhook_url) pair is either set
    # together or NULL together. The provider determines the payload schema
    # (e.g. Google Chat Cards v2) and the accepted hosts (allowlist per
    # provider, SSRF defense at the source). See `app.services.notifications`.
    provider: Mapped[str | None] = mapped_column(String(32))
    webhook_url: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )


class CdnAllowlist(Base):
    """Admin-curated extension to the built-in trusted-CDN set.

    Built-in defaults live in `Settings.trusted_cdn_hosts`; rows in this
    table are unioned with that env list at scan time, letting admins
    expand the allowlist without a redeploy.
    """

    __tablename__ = "cdn_allowlist"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    host: Mapped[str] = mapped_column(String(255), unique=True)
    added_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
