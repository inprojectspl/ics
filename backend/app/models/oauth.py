"""OAuth 2.1 Authorization Server for MCP clients (RFC 8707, PKCE S256)."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class OAuthClient(Base):
    """Public clients have `client_secret_hash IS NULL` and must use PKCE.
    `allowed_audiences` lists the RFC 8707 `resource` values /authorize accepts."""

    __tablename__ = "oauth_clients"
    __table_args__ = (
        CheckConstraint(
            "client_type IN ('public','confidential')",
            name="ck_oauth_clients_type",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    client_id: Mapped[str] = mapped_column(String(128))
    client_secret_hash: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str] = mapped_column(String(255))
    client_type: Mapped[str] = mapped_column(String(16))
    redirect_uris: Mapped[list[str]] = mapped_column(ARRAY(String))
    allowed_scopes: Mapped[list[str]] = mapped_column(ARRAY(String), server_default="{ics}")
    allowed_audiences: Mapped[list[str]] = mapped_column(ARRAY(String))
    owner_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    is_dynamic: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class OAuthAuthCode(Base):
    """Short-lived authorization codes (typically 10 min TTL).

    `resource` MUST match the value passed to /token; mismatch = 400. PKCE
    `code_challenge_method='S256'` is enforced, the only method the spec allows.
    """

    __tablename__ = "oauth_auth_codes"
    __table_args__ = (
        CheckConstraint(
            "code_challenge_method = 'S256'",
            name="ck_oauth_auth_codes_pkce_method",
        ),
    )

    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[UUID] = mapped_column(ForeignKey("oauth_clients.id", ondelete="CASCADE"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    redirect_uri: Mapped[str] = mapped_column(Text)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String))
    resource: Mapped[str] = mapped_column(Text)
    code_challenge: Mapped[str] = mapped_column(String(128))
    code_challenge_method: Mapped[str] = mapped_column(String(8))
    nonce: Mapped[str | None] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class OAuthRefreshToken(Base):
    """Refresh tokens with rotation + reuse detection.

    Spec mandate: public clients MUST rotate refresh tokens (OAuth 2.1 §4.3.1).
    Re-using an already-rotated token revokes the whole `parent_id` chain,
    since it signals a leaked token. Active tokens have `revoked_at IS NULL`.
    """

    __tablename__ = "oauth_refresh_tokens"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    token_hash: Mapped[str] = mapped_column(String(64))
    client_id: Mapped[UUID] = mapped_column(ForeignKey("oauth_clients.id", ondelete="CASCADE"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String))
    resource: Mapped[str] = mapped_column(Text)
    jwt_id: Mapped[str] = mapped_column(String(64))
    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("oauth_refresh_tokens.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    rotated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    revocation_reason: Mapped[str | None] = mapped_column(String(64))


class OAuthJTIBlacklist(Base):
    """Revoked-before-expiry JWT IDs. Cleanup job drops rows past expires_at."""

    __tablename__ = "oauth_jti_blacklist"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    revoked_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
