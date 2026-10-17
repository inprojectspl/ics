"""Shared `APIRouter` + cross-endpoint helpers for auth."""

from __future__ import annotations

from fastapi import APIRouter, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import passwords, tokens
from app.auth import domain_of
from app.config import Settings
from app.constants import TokenPurpose
from app.errors import ApiError
from app.models import AuthAttempt

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Generic auth-failure message: never leak whether the email exists.
_AUTH_FAIL = "invalid email or password"


def _verify_token_or_400(purpose: TokenPurpose, token: str) -> str:
    try:
        return tokens.verify(purpose, token)
    except tokens.TokenExpired:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "token_expired", "token expired") from None
    except tokens.TokenInvalid:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "token_invalid", "invalid token") from None


def _validate_password_or_400(pwd: str) -> None:
    try:
        passwords.validate_password(pwd)
    except passwords.WeakPasswordError as e:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "weak_password", str(e)) from e


def _role_from_domain(email: str, settings: Settings) -> str:
    return "user" if domain_of(email) in settings.allowed_domain_list else "external"


async def _record_attempt(
    session: AsyncSession,
    email: str,
    ip_hash_: str,
    succeeded: bool,
) -> None:
    session.add(AuthAttempt(email=email, ip_hash=ip_hash_, succeeded=succeeded))


_DUMMY_HASH_CACHE: str | None = None


def _dummy_hash() -> str:
    """Constant-time decoy for missing-user logins. Lazy to avoid blocking
    import with ~200ms argon2 work."""
    global _DUMMY_HASH_CACHE
    if _DUMMY_HASH_CACHE is None:
        _DUMMY_HASH_CACHE = passwords.hash_password("constant-time-dummy-x9q7m2")
    return _DUMMY_HASH_CACHE
