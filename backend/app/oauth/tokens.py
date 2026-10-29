"""JWT signing, refresh token rotation and the JTI blacklist.

Refresh tokens are stored hashed and chained via `parent_id`; reusing a
rotated token revokes the whole chain (OAuth security BCP §2.2.2).
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import cast

from joserfc import jwt
from sqlalchemy import CursorResult, delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import OAuthJTIBlacklist, OAuthRefreshToken, User
from app.oauth.keys import signing_key, verification_key
from app.slug import generate_token

# The only accepted signature algorithm. Passed explicitly on every encode
# and decode so a token with a tampered `alg` header cannot go through any
# verification path other than the one we sign with.
_ALGORITHMS = ["RS256"]


def hash_token(token: str) -> str:
    """SHA-256 hex digest, the store-only form for refresh tokens."""
    return sha256(token.encode("utf-8")).hexdigest()


def sign_access_jwt(
    *,
    settings: Settings,
    user: User,
    client_id_external: str,
    scopes: list[str],
    audience: str,
    jti: str | None = None,
) -> tuple[str, str]:
    """Sign an access JWT. Returns (jwt_compact, jti)."""
    now = int(time.time())
    exp = now + settings.oauth_access_token_ttl
    jti = jti or uuid.uuid4().hex
    issuer = settings.oauth_issuer or settings.base_url
    claims = {
        "iss": issuer,
        "sub": str(user.id),
        "aud": audience,
        "client_id": client_id_external,
        "scope": " ".join(scopes),
        "jti": jti,
        "iat": now,
        "nbf": now,
        "exp": exp,
        "email": user.email,
        "email_verified": user.email_verified_at is not None,
    }
    header = {"alg": "RS256", "kid": settings.oauth_kid, "typ": "JWT"}
    token = jwt.encode(header, claims, signing_key(settings), algorithms=_ALGORITHMS)
    return token, jti


def verify_access_jwt(settings: Settings, token: str, *, expected_audience: str) -> dict:
    """Verify signature and claims; raises joserfc `JoseError` on mismatch.

    Does not check the JTI blacklist; the resource server dependency does.
    """
    issuer = settings.oauth_issuer or settings.base_url
    registry = jwt.JWTClaimsRegistry(
        iss={"essential": True, "values": [issuer]},
        aud={"essential": True, "values": [expected_audience]},
        exp={"essential": True},
        iat={"essential": True},
        sub={"essential": True},
    )
    decoded = decode_access_jwt(settings, token)
    registry.validate(decoded.claims)
    return dict(decoded.claims)


def decode_access_jwt(settings: Settings, token: str) -> jwt.Token:
    """Verify the signature only, without claim rules.

    Separate from `verify_access_jwt` because the revocation endpoint does
    not know the audience the token was issued for, yet still has to read
    its `jti` and `exp`. The signature is checked the same way.
    """
    return jwt.decode(token, verification_key(settings), algorithms=_ALGORITHMS)


async def is_jti_revoked(session: AsyncSession, jti: str) -> bool:
    return (
        await session.scalar(select(OAuthJTIBlacklist.jti).where(OAuthJTIBlacklist.jti == jti))
    ) is not None


async def blacklist_jti(session: AsyncSession, *jtis: str, expires_at_epoch: int) -> None:
    """One insert for all `jtis`. Idempotent: revoking an already revoked
    token (or two revokes racing) is not an error."""
    if not jtis:
        return
    expires_at = datetime.fromtimestamp(expires_at_epoch, tz=UTC)
    await session.execute(
        pg_insert(OAuthJTIBlacklist)
        .values([{"jti": jti, "expires_at": expires_at} for jti in jtis])
        .on_conflict_do_nothing(index_elements=[OAuthJTIBlacklist.jti])
    )


async def issue_refresh_token(
    session: AsyncSession,
    *,
    settings: Settings,
    client_uuid: uuid.UUID,
    user_id: uuid.UUID,
    scopes: list[str],
    resource: str,
    jwt_id: str,
    parent_id: uuid.UUID | None = None,
) -> tuple[str, OAuthRefreshToken]:
    raw = generate_token(48)
    rec = OAuthRefreshToken(
        token_hash=hash_token(raw),
        client_id=client_uuid,
        user_id=user_id,
        scopes=scopes,
        resource=resource,
        jwt_id=jwt_id,
        parent_id=parent_id,
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.oauth_refresh_token_ttl),
    )
    session.add(rec)
    await session.flush()
    return raw, rec


async def revoke_refresh_chain(
    session: AsyncSession, start: OAuthRefreshToken, reason: str, *, access_ttl: int
) -> None:
    """Walk the parent_id chain backwards and the children forwards, revoking
    every token in the family and blacklisting the access JWT issued with each.
    Triggered by a revocation request or when a rotated token is reused
    (= token leak detected)."""
    now = datetime.now(UTC)
    issued: list[tuple[str, datetime | None]] = []
    visited: set[uuid.UUID] = set()
    queue: list[OAuthRefreshToken] = [start]
    while queue:
        cur = queue.pop()
        if cur.id in visited:
            continue
        visited.add(cur.id)
        cur.revoked_at = now
        cur.revocation_reason = reason
        issued.append((cur.jwt_id, cur.created_at))
        if cur.parent_id and cur.parent_id not in visited:
            parent = await session.get(OAuthRefreshToken, cur.parent_id)
            if parent:
                queue.append(parent)
        children = (
            await session.scalars(
                select(OAuthRefreshToken).where(OAuthRefreshToken.parent_id == cur.id)
            )
        ).all()
        for ch in children:
            if ch.id not in visited:
                queue.append(ch)
    await _blacklist_live_jwts(session, issued, now=now, access_ttl=access_ttl)


async def revoke_user_grants(
    session: AsyncSession, user_id: uuid.UUID, *, reason: str, access_ttl: int
) -> int:
    """Sign every OAuth client of a user out: revoke their live refresh tokens
    and blacklist the access JWTs still in use. Returns the refresh tokens
    revoked."""
    now = datetime.now(UTC)
    revoked = await session.execute(
        update(OAuthRefreshToken)
        .where(OAuthRefreshToken.user_id == user_id, OAuthRefreshToken.revoked_at.is_(None))
        .values(revoked_at=now, revocation_reason=reason)
    )
    # A rotated token is revoked already, yet its access JWT may still live.
    issued = await session.execute(
        select(OAuthRefreshToken.jwt_id, OAuthRefreshToken.created_at).where(
            OAuthRefreshToken.user_id == user_id,
            OAuthRefreshToken.created_at > now - timedelta(seconds=access_ttl),
        )
    )
    await _blacklist_live_jwts(session, issued.tuples().all(), now=now, access_ttl=access_ttl)
    return cast(CursorResult, revoked).rowcount or 0


async def _blacklist_live_jwts(
    session: AsyncSession,
    issued: Sequence[tuple[str, datetime | None]],
    *,
    now: datetime,
    access_ttl: int,
) -> None:
    """Blacklist the access JWT of each `(jwt_id, created_at)` refresh token
    that can still be in use: it is issued with the refresh token and lives
    `access_ttl`. `created_at` is unset on a token added in this transaction."""
    live_since = now - timedelta(seconds=access_ttl)
    live = [jti for jti, created in issued if created is None or created > live_since]
    # The blacklist row only has to outlast the JWTs it blocks.
    await blacklist_jti(session, *live, expires_at_epoch=int(now.timestamp()) + access_ttl)


async def find_active_refresh(
    session: AsyncSession, token_hash_value: str
) -> OAuthRefreshToken | None:
    """Find refresh by hash. Returns row regardless of revoked_at; caller
    distinguishes (rotated tokens are revoked but we still need them for
    reuse detection). The row stays locked until the transaction ends, so two
    concurrent rotations of one token run one after the other and the second
    sees the first as reuse."""
    return await session.scalar(
        select(OAuthRefreshToken)
        .where(OAuthRefreshToken.token_hash == token_hash_value)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def cleanup_expired(session: AsyncSession) -> int:
    """Drop expired auth codes and JTI blacklist entries. Called by Arq cron."""
    from app.models import OAuthAuthCode

    now = datetime.now(UTC)
    deleted = 0
    for model in (OAuthAuthCode, OAuthJTIBlacklist):
        res = await session.execute(delete(model).where(model.expires_at < now))
        deleted += cast(CursorResult, res).rowcount or 0
    return deleted
