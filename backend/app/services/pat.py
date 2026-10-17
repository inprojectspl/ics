"""Personal access tokens (ADR-0020): `ics_pat_<prefix>_<secret>`. Only an
HMAC-SHA256 of the whole token is stored, keyed with a pepper derived from the
secret key; the token is long and random, so a slow hash would add nothing.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import CursorResult, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from app import audit
from app.config import get_settings
from app.domain_errors import InvalidInputError, LimitExceededError
from app.models import PersonalAccessToken, User
from app.util import now as utc_now

TOKEN_PREFIX = "ics_pat_"
MAX_ACTIVE_TOKENS = 5
MAX_LIFETIME = timedelta(days=180)
LAST_USED_RESOLUTION = timedelta(minutes=5)
# `ics:write` is reserved until a use case needs it (ADR-0020).
ISSUED_SCOPES: tuple[str, ...] = ("ics:read",)


def _pepper() -> bytes:
    key = get_settings().secret_key.encode("utf-8")
    return hmac.new(key, b"ics:personal-access-token:v1", hashlib.sha256).digest()


def hash_token(token: str) -> str:
    return hmac.new(_pepper(), token.encode("utf-8"), hashlib.sha256).hexdigest()


def parse_prefix(token: str) -> str | None:
    """The lookup prefix of a well-formed token, None otherwise."""
    if not token.startswith(TOKEN_PREFIX):
        return None
    prefix, sep, secret = token[len(TOKEN_PREFIX) :].partition("_")
    if not sep or len(prefix) != 8 or not secret:
        return None
    try:
        bytes.fromhex(prefix)
    except ValueError:
        return None
    return prefix


def _active(user_id: UUID, now: datetime):
    return (
        PersonalAccessToken.user_id == user_id,
        PersonalAccessToken.revoked_at.is_(None),
        PersonalAccessToken.expires_at > now,
    )


async def create(
    session: AsyncSession,
    *,
    user: User,
    name: str,
    expires_at: datetime,
) -> tuple[PersonalAccessToken, str]:
    """Issue a token and return it with its plaintext, which is never stored."""
    now = utc_now()
    if expires_at.tzinfo is None or expires_at <= now or expires_at > now + MAX_LIFETIME:
        raise InvalidInputError(
            "pat_expiry_invalid",
            f"expires_at must be in the future and at most {MAX_LIFETIME.days} days away",
            field="expires_at",
        )
    # Lock the user row so two parallel requests cannot both pass the limit.
    await session.execute(select(User.id).where(User.id == user.id).with_for_update())
    active = await session.scalar(
        select(func.count()).select_from(PersonalAccessToken).where(*_active(user.id, now))
    )
    if (active or 0) >= MAX_ACTIVE_TOKENS:
        raise LimitExceededError("pat_limit", f"at most {MAX_ACTIVE_TOKENS} active tokens per user")

    prefix = secrets.token_hex(4)
    plaintext = f"{TOKEN_PREFIX}{prefix}_{secrets.token_urlsafe(32)}"
    token = PersonalAccessToken(
        user_id=user.id,
        name=name,
        token_prefix=prefix,
        token_hash=hash_token(plaintext),
        scopes=list(ISSUED_SCOPES),
        expires_at=expires_at,
    )
    session.add(token)
    await session.flush()
    await audit.record(
        session,
        actor=user,
        action="pat_created",
        target=f"pat:{token.id}",
        payload={"prefix": prefix, "scopes": token.scopes, "expires_at": expires_at.isoformat()},
    )
    return token, plaintext


async def verify(session: AsyncSession, token: str) -> PersonalAccessToken | None:
    """The token row when the token is valid, not revoked and not expired."""
    prefix = parse_prefix(token)
    if prefix is None:
        return None
    digest = hash_token(token)
    candidates = (
        await session.scalars(
            select(PersonalAccessToken).where(PersonalAccessToken.token_prefix == prefix)
        )
    ).all()
    match = None
    for row in candidates:
        if hmac.compare_digest(row.token_hash, digest):
            match = row
    now = utc_now()
    if match is None or match.revoked_at is not None or match.expires_at <= now:
        return None
    return match


async def record_use(session: AsyncSession, token: PersonalAccessToken) -> bool:
    """Stamp `last_used_at` at most once per `LAST_USED_RESOLUTION`: a client
    polling with the token would otherwise write the row on every request.
    Returns whether the row changed (the caller commits only then)."""
    now = utc_now()
    stale = now - LAST_USED_RESOLUTION
    if token.last_used_at is not None and token.last_used_at >= stale:
        return False
    result = await session.execute(
        update(PersonalAccessToken)
        .where(
            PersonalAccessToken.id == token.id,
            or_(
                PersonalAccessToken.last_used_at.is_(None),
                PersonalAccessToken.last_used_at < stale,
            ),
        )
        .values(last_used_at=now)
        .execution_options(synchronize_session=False)
    )
    if cast(CursorResult, result).rowcount == 0:
        # A concurrent request stamped it first.
        return False
    set_committed_value(token, "last_used_at", now)
    return True


async def list_for_user(session: AsyncSession, user_id: UUID) -> list[PersonalAccessToken]:
    """Tokens not revoked, newest first; expired ones stay visible until revoked."""
    rows = await session.scalars(
        select(PersonalAccessToken)
        .where(PersonalAccessToken.user_id == user_id, PersonalAccessToken.revoked_at.is_(None))
        .order_by(PersonalAccessToken.created_at.desc())
    )
    return list(rows.all())


async def revoke(
    session: AsyncSession, *, token_id: UUID, user_id: UUID, actor: User
) -> PersonalAccessToken | None:
    """Revoke one token of `user_id`; None when it does not belong to them."""
    token = await session.get(PersonalAccessToken, token_id)
    if token is None or token.user_id != user_id:
        return None
    if token.revoked_at is None:
        token.revoked_at = utc_now()
        await audit.record(
            session,
            actor=actor,
            action="pat_revoked",
            target=f"pat:{token.id}",
            payload={"prefix": token.token_prefix},
        )
    return token


async def revoke_all_for_user(
    session: AsyncSession, *, user_id: UUID, actor: User | str, reason: str
) -> int:
    """Revoke every token of a user that is not revoked yet; returns the count."""
    result = await session.execute(
        update(PersonalAccessToken)
        .where(PersonalAccessToken.user_id == user_id, PersonalAccessToken.revoked_at.is_(None))
        .values(revoked_at=utc_now())
        .returning(PersonalAccessToken.id)
    )
    count = len(result.all())
    if count:
        await audit.record(
            session,
            actor=actor,
            action="pat_revoked",
            target=f"user:{user_id}",
            payload={"all": True, "count": count, "reason": reason},
        )
    return count
