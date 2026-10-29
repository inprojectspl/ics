"""Accounts and login bookkeeping: users, auth attempts, e-mail outbox."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.constants import DEFAULT_BUNDLE_MAX_BYTES, AuthMethod
from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    # The UNIQUE constraint provides a B-tree index; `index=True` would duplicate it.
    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(32), default="user", server_default="user")
    auth_method: Mapped[AuthMethod] = mapped_column(
        String(32), default="google_sso", server_default="google_sso"
    )
    password_hash: Mapped[str | None] = mapped_column(Text)
    email_verified_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    locked_until: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    storage_quota_bytes: Mapped[int] = mapped_column(
        BigInteger, default=1024 * 1024 * 1024, server_default=str(1024 * 1024 * 1024)
    )
    # Auto-approve html bundles the scanner marks `critical`. Per user because
    # trust belongs to the author (report generators emit `eval()` the owner
    # cannot remove); the scan still runs and records findings.
    html_autobypass: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Cap on a single html bundle upload (does not accumulate like the quota).
    # The default is in constants because the migration and tests read it too.
    bundle_max_bytes: Mapped[int] = mapped_column(
        BigInteger,
        default=DEFAULT_BUNDLE_MAX_BYTES,
        server_default=str(DEFAULT_BUNDLE_MAX_BYTES),
    )
    # Language of e-mails and pages the backend renders for this user (`pl`,
    # `en`). NULL means "not chosen": the request's Accept-Language decides.
    locale: Mapped[str | None] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    last_login_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    # Not a column: set per request by `app.auth.get_current_user`. A request
    # authenticated with a bearer token (personal access or OAuth) never gets
    # admin powers (ADR-0020), so admin bypasses check `acts_as_admin`, not `role`.
    token_request = False

    @property
    def acts_as_admin(self) -> bool:
        return self.role == "admin" and not self.token_request


class AuthAttempt(Base):
    """Rate-limiting + lockout counter persisted (Redis is primary; DB is audit + fallback)."""

    __tablename__ = "auth_attempts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    succeeded: Mapped[bool] = mapped_column(default=False)
    timestamp: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), index=True
    )


class EmailOutbox(Base):
    """Every outgoing e-mail, stored before SMTP delivery is attempted
    (admin UI, tests, retries); `sent_at` is set once SMTP accepted it."""

    __tablename__ = "email_outbox"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    to_email: Mapped[str] = mapped_column(String(320), index=True)
    subject: Mapped[str] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)
    body_html: Mapped[str | None] = mapped_column(Text)
    purpose: Mapped[str] = mapped_column(
        String(32)
    )  # invite | reset | verify | magic_link | notification
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), index=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
