from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import ratelimit, session_store
from app.config import Settings, get_settings
from app.constants import AuthMethod
from app.db import get_session
from app.errors import ApiError
from app.models import User
from app.redis_client import get_redis
from app.services import pat
from app.session_store import SESSION_KEY, SESSION_SID_KEY


def domain_of(email: str) -> str:
    return email.split("@")[-1].lower()


def _is_locked(user: User) -> bool:
    return user.locked_until is not None and user.locked_until > datetime.now(UTC)


def _bearer_401(settings: Settings, detail: str, *, error: str = "invalid_token") -> HTTPException:
    """401 for the Bearer path, always with `WWW-Authenticate` (RFC 6750 §3).

    The MCP client uses this header to tell "refresh the token" apart from
    application-level 401s (e.g. the share-password challenge). A bearer 401
    without it would disable the client's auto-refresh."""
    return ApiError(
        status.HTTP_401_UNAUTHORIZED,
        "invalid_token",
        detail,
        headers={
            "WWW-Authenticate": (
                f'Bearer error="{error}", '
                f'resource_metadata="{settings.base_url.rstrip("/")}'
                '/.well-known/oauth-protected-resource"'
            )
        },
    )


async def _get_or_create_user(
    session: AsyncSession,
    email: str,
    display_name: str | None = None,
    auth_method: AuthMethod = "google_sso",
) -> User:
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            email=email,
            display_name=display_name or email.split("@")[0],
            auth_method=auth_method,
            email_verified_at=datetime.now(UTC) if auth_method == "google_sso" else None,
        )
        session.add(user)
        await session.flush()
    user.last_login_at = datetime.now(UTC)
    await session.commit()
    return user


def _bearer_token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return None


async def _validate_bearer(
    request: Request, session: AsyncSession, settings: Settings, token: str
) -> User:
    """Resource-server side of OAuth 2.1 / MCP: RS256 against our JWKS, audience
    bound to ICS_MCP_RESOURCE_URI (RFC 8707), `jti` revocation checked."""
    from joserfc.errors import JoseError

    from app.oauth import tokens as oauth_tokens

    if not settings.mcp_resource_uri:
        raise ApiError(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "oauth_not_configured",
            "OAuth: ICS_MCP_RESOURCE_URI not configured",
        )
    try:
        claims = oauth_tokens.verify_access_jwt(
            settings, token, expected_audience=settings.mcp_resource_uri
        )
    except JoseError as e:
        raise _bearer_401(settings, f"invalid_token: {e.__class__.__name__}") from e

    jti = claims.get("jti")
    if jti and await oauth_tokens.is_jti_revoked(session, jti):
        raise _bearer_401(settings, "token_revoked")

    sub = claims.get("sub")
    if not sub:
        raise _bearer_401(settings, "invalid_token: no sub")
    user = await session.get(User, UUID(sub))
    if user is None:
        raise _bearer_401(settings, "user not found")
    if _is_locked(user):
        raise ApiError(status.HTTP_403_FORBIDDEN, "account_locked", "user locked")

    request.state.oauth_client_id_external = claims.get("client_id")
    request.state.oauth_scopes = (claims.get("scope") or "").split()
    request.state.oauth_jti = jti
    request.state.oauth_audience = claims.get("aud")
    request.state.oauth_transport = "bearer"
    return user


async def _validate_pat(
    request: Request, session: AsyncSession, settings: Settings, token: str
) -> User:
    """Personal access token (ADR-0020): same 401 contract as the OAuth path,
    evaluated as an ordinary user (`User.token_request`), limited like MCP."""
    row = await pat.verify(session, token)
    if row is None:
        raise _bearer_401(settings, "invalid personal access token")
    user = await session.get(User, row.user_id)
    if user is None:
        raise _bearer_401(settings, "user not found")
    if _is_locked(user):
        raise ApiError(status.HTTP_403_FORBIDDEN, "account_locked", "user locked")
    await ratelimit.enforce(get_redis(), ratelimit.PAT_API, str(user.id), "pat_rate_limited")
    # Persisted even on read-only requests, but only when the stamp moved.
    if await pat.record_use(session, row):
        await session.commit()

    user.token_request = True
    request.state.oauth_scopes = list(row.scopes)
    request.state.oauth_transport = "pat"
    return user


# A token works without the browser, so a leaked one must not carry admin
# powers (ADR-0020): the holder acts as an ordinary user.
_TOKEN_TRANSPORTS = frozenset({"bearer", "pat"})


async def get_current_user(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> User:
    # The scope gate may have authenticated this request already.
    cached = getattr(request.state, "current_user", None)
    if cached is not None:
        return cached
    user = await _authenticate(request, session, settings)
    request.state.current_user = user
    # The flag lives on the (identity-mapped) instance, so reset it for every
    # other transport rather than relying on the class default.
    user.token_request = getattr(request.state, "oauth_transport", None) in _TOKEN_TRANSPORTS
    return user


async def _authenticate(request: Request, session: AsyncSession, settings: Settings) -> User:
    # 1) Bearer token: personal access token or OAuth 2.1 / MCP JWT
    token = _bearer_token(request)
    if token:
        if token.startswith(pat.TOKEN_PREFIX):
            return await _validate_pat(request, session, settings, token)
        return await _validate_bearer(request, session, settings, token)

    # 2) Dev stub SSO
    if settings.dev_stub_sso:
        stub_email = request.headers.get("x-dev-user", "dev@example.com")
        if domain_of(stub_email) not in settings.allowed_domain_list:
            raise ApiError(status.HTTP_403_FORBIDDEN, "domain_not_allowed", "domain not allowed")
        request.state.oauth_transport = "dev_stub"
        return await _get_or_create_user(session, stub_email)

    # 3) Cookie session (frontend)
    user_id: str | None = request.session.get(SESSION_KEY)
    if not user_id:
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            "not_authenticated",
            "not authenticated",
            headers={
                "WWW-Authenticate": (
                    f'Bearer resource_metadata="{settings.base_url.rstrip("/")}'
                    '/.well-known/oauth-protected-resource", scope="ics"'
                )
            },
        )

    # The signed cookie outlives logout; without this check a stolen one keeps working (CWE-613).
    sid = request.session.get(SESSION_SID_KEY)
    if sid is None:
        request.session.clear()
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            "session_invalid",
            "session has no sid, log in again",
        )
    redis = get_redis()
    if await session_store.is_revoked(redis, sid):
        request.session.clear()
        raise ApiError(status.HTTP_401_UNAUTHORIZED, "session_revoked", "session revoked")

    user = await session.get(User, UUID(user_id))
    if user is None:
        raise ApiError(status.HTTP_401_UNAUTHORIZED, "user_not_found", "user not found")
    if _is_locked(user):
        await session_store.revoke_sid(redis, sid, user_id=user_id)
        request.session.clear()
        raise ApiError(status.HTTP_403_FORBIDDEN, "account_locked", "account locked")
    request.state.oauth_transport = "cookie"
    return user


async def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    # `acts_as_admin` is False for a bearer token (PAT or OAuth): /api/admin/*
    # is browser only (ADR-0020).
    if not user.acts_as_admin:
        raise ApiError(status.HTTP_403_FORBIDDEN, "admin_required", "admin required")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]

# Methods a read-only token may call, and scopes that grant nothing more.
READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
READ_ONLY_SCOPES = frozenset({"ics:read"})


async def enforce_token_scope(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    """App-wide dependency (ADR-0020): a bearer token whose scopes are all
    read-only (a PAT with `ics:read`) may not call a writing method. OAuth
    tokens of ics-mcp carry `ics` and keep writing. Authentication failures
    are left to the route, which answers them with its own 401."""
    if request.method in READ_METHODS or _bearer_token(request) is None:
        return
    try:
        await get_current_user(request, session, settings)
    except HTTPException:
        return
    scopes = set(getattr(request.state, "oauth_scopes", None) or ())
    if scopes and scopes <= READ_ONLY_SCOPES:
        raise ApiError(status.HTTP_403_FORBIDDEN, "insufficient_scope", "the token is read only")


AdminUser = Annotated[User, Depends(require_admin)]


async def get_optional_user(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> User | None:
    """`get_current_user`, but "nobody is logged in" is a valid answer.

    For endpoints like the link resolver whose answer differs for anonymous callers.
    Every auth error, 403 included, collapses to None so the reason does not leak.
    """
    try:
        return await get_current_user(request, session, settings)
    except HTTPException:
        return None


OptionalUser = Annotated[User | None, Depends(get_optional_user)]


async def require_mcp_rate_limit(user: CurrentUser) -> None:
    """Dependency: blocks when this user exceeded the MCP_API limit; keyed by user,
    not IP, since agents often share a NAT."""
    await ratelimit.enforce(get_redis(), ratelimit.MCP_API, str(user.id), "mcp_rate_limited")
