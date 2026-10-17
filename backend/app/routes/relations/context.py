"""Agent context pack endpoint (ADR-0019)."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, ratelimit
from app.auth import CurrentUser
from app.db import get_session
from app.errors import ApiError
from app.redis_client import get_redis
from app.services.context_pack import DEFAULT_BUDGET, MAX_BUDGET, MAX_DEPTH, ContextRequest
from app.services.context_pack_output import build

from ._router import router

_MAX_ANCESTORS = 20


def _split(values: list[str] | None) -> tuple[str, ...]:
    """`ancestors=4700,4650` and `ancestors=4700&ancestors=4650` alike."""
    out = [v.strip() for raw in values or [] for v in raw.split(",") if v.strip()]
    if len(out) > _MAX_ANCESTORS:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "external_ref_invalid", "too many ancestors")
    return tuple(out)


@router.get("/context")
async def get_context_pack(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    request: Request,
    wp: Annotated[str, Query(min_length=1, max_length=200)],
    system: Literal["openproject", "project_standard"] = "openproject",
    ancestors: Annotated[list[str] | None, Query()] = None,
    project: Annotated[str | None, Query(max_length=100)] = None,
    scope: Annotated[str | None, Query(max_length=100)] = None,
    depth: Annotated[int, Query(ge=0, le=MAX_DEPTH)] = 1,
    budget_tokens: Annotated[int, Query(ge=200, le=MAX_BUDGET)] = DEFAULT_BUDGET,
    include: Annotated[list[Literal["references", "deliverables"]] | None, Query()] = None,
) -> dict:
    """Documents of one task for the caller: linked, inherited, key documents
    and graph neighbours, ordered and cut to `budget_tokens`. An unknown task
    or one with nothing visible is an empty list, never a 404."""
    redis = get_redis()
    scope_key = str(user.id)
    if not await ratelimit.check_and_incr(redis, ratelimit.CONTEXT_PACK, scope_key):
        retry = await ratelimit.retry_after_seconds(redis, ratelimit.CONTEXT_PACK, scope_key)
        raise ApiError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "rate_limited",
            "too many context requests",
            headers={"Retry-After": str(retry)},
        )
    req = ContextRequest(
        system=system,
        wp=wp.strip(),
        ancestors=_split(ancestors),
        project=project,
        scope=scope,
        depth=depth,
        budget_tokens=budget_tokens,
        include=frozenset(include or ()),
    )
    return await build(session, user, req, transport=audit.request_transport(request))
