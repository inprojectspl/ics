"""Micro-application management API, the app launch step, and the private
API of the shared runtime broker.

plan/apply accept programmatic authentication only (OAuth bearer of
ICS-MCP or a personal access token); the browser panel reads status and
sends control actions with its cookie session, never uploads a package.
"""

from __future__ import annotations

import hmac
import mimetypes
from typing import Annotated, Any
from urllib.parse import quote, urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app import ratelimit
from app.auth import CurrentUser, OptionalUser
from app.config import Settings, get_settings
from app.db import get_session
from app.errors import ApiError
from app.redis_client import get_redis
from app.services.micro_applications import (
    contract,
    control,
    document,
    hosts,
    operations,
    people,
    plan,
    runtime,
)
from app.services.micro_applications import status as status_svc
from app.services.micro_applications.common import ENVIRONMENT

router = APIRouter(prefix="/api/micro-applications", tags=["micro-applications"])
internal_router = APIRouter(prefix="/api/internal/microapps", include_in_schema=False)

Session = Annotated[AsyncSession, Depends(get_session)]
AppSettings = Annotated[Settings, Depends(get_settings)]

_PROGRAMMATIC = frozenset({"bearer", "pat"})


def require_enabled(settings: Settings) -> None:
    if not settings.microapps_enabled:
        raise ApiError(
            status.HTTP_404_NOT_FOUND, "microapps_disabled", "micro-applications are off"
        )


def _require_programmatic(request: Request) -> None:
    if getattr(request.state, "oauth_transport", None) not in _PROGRAMMATIC:
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            "programmatic_auth_required",
            "plan and apply need a bearer token (ICS-MCP) or a personal access token",
        )


class PlanFile(BaseModel):
    path: str = Field(max_length=200)
    content_text: str | None = None
    content_base64: str | None = None


class PlanRequest(BaseModel):
    files: list[PlanFile] = Field(min_length=1, max_length=60)
    asset_id: UUID | None = None
    project_id: UUID | None = None
    # What the release changes, in the author's words (the version history).
    change_note: str | None = Field(default=None, max_length=500)


class ApplyRequest(BaseModel):
    digest: str = Field(max_length=80)
    expected_generation: int = Field(ge=0)
    idempotency_key: str | None = Field(
        default=None, min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"
    )


class ControlRequest(BaseModel):
    action: str
    expected_generation: int = Field(ge=0)
    idempotency_key: str | None = Field(
        default=None, min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"
    )


class AccessRequest(BaseModel):
    user_email: str | None = Field(default=None, max_length=320)
    project_id: UUID | None = None
    roles: list[str] = Field(default_factory=list, max_length=20)
    permissions: list[str] = Field(default_factory=list, max_length=50)
    can_open: bool | None = None


def _key(body_key: str | None, header_key: str | None) -> str:
    key = header_key or body_key
    if not key:
        raise ApiError(
            status.HTTP_428_PRECONDITION_REQUIRED,
            "precondition_required",
            "an idempotency key is required (body idempotency_key or Idempotency-Key)",
        )
    if body_key and header_key and body_key != header_key:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "idempotency_key_mismatch",
            "body and header idempotency keys differ",
        )
    return key


@router.get("/contract")
async def get_contract(
    user: CurrentUser, settings: AppSettings, section: str | None = None
) -> dict[str, Any]:
    require_enabled(settings)
    full = contract.build(settings)
    if section is None:
        return full
    if section not in contract.SECTIONS:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "invalid_argument",
            "unknown section",
            extra={"field": "section", "allowed": list(contract.SECTIONS)},
        )
    return {
        **{k: v for k, v in full.items() if k != "sections"},
        "section": section,
        "content": full["sections"][section],
    }


@router.post("/plans", status_code=status.HTTP_201_CREATED)
async def create_plan(
    body: PlanRequest, request: Request, user: CurrentUser, session: Session, settings: AppSettings
) -> dict[str, Any]:
    require_enabled(settings)
    _require_programmatic(request)
    await ratelimit.enforce(
        get_redis(),
        ratelimit.MICROAPP_PLAN,
        str(user.id),
        "too many plans; fix the diagnostics of the last one first",
    )
    return await plan.create_plan(
        session,
        settings,
        user,
        files=[f.model_dump(exclude_none=True) for f in body.files],
        asset_id=body.asset_id,
        project_id=body.project_id,
        change_note=body.change_note,
    )


@router.post("/plans/{plan_id}/apply")
async def apply_plan(
    plan_id: str,
    body: ApplyRequest,
    request: Request,
    response: Response,
    user: CurrentUser,
    session: Session,
    settings: AppSettings,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    require_enabled(settings)
    _require_programmatic(request)
    view, created = await operations.apply_plan(
        session,
        settings,
        user,
        plan_id,
        digest=body.digest,
        expected_generation=body.expected_generation,
        idempotency_key=_key(body.idempotency_key, idempotency_key),
    )
    response.status_code = status.HTTP_202_ACCEPTED if created else status.HTTP_200_OK
    return {**view, "replayed": not created}


@router.get("/operations/{op_id}")
async def get_operation(
    op_id: str, user: CurrentUser, session: Session, settings: AppSettings
) -> dict[str, Any]:
    require_enabled(settings)
    return await operations.get_operation(session, settings, user, op_id)


@router.get("")
async def list_apps(
    user: CurrentUser,
    session: Session,
    settings: AppSettings,
    q: Annotated[str | None, Query(max_length=200)] = None,
    state: Annotated[
        str | None, Query(pattern="^(enabled|suspended|running|ready|sleeping)$")
    ] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    require_enabled(settings)
    return await status_svc.list_apps(
        session, settings, user, q=q, state=state, offset=offset, limit=limit
    )


@router.get("/launch")
async def launch(
    request: Request,
    user: OptionalUser,
    session: Session,
    settings: AppSettings,
    host: Annotated[str, Query(max_length=200)],
    state: Annotated[str, Query(max_length=128)],
) -> RedirectResponse:
    """Second step of the app sign-in: the browser comes from the app origin
    with a start bound to it; ICS answers with a one-time code for that start."""
    require_enabled(settings)
    if user is None:
        back = f"/api/micro-applications/launch?{urlencode({'host': host, 'state': state})}"
        return RedirectResponse(f"/#login?next={quote(back, safe='')}", status_code=302)
    code = await runtime.issue_launch_code(session, settings, user, host, state)
    return callback_redirect(settings, host, code)


def callback_redirect(settings: Settings, host: str, code: str) -> RedirectResponse:
    """Hand a one-time launch code back to the app origin that started it."""
    target = f"{settings.microapps_app_scheme}://{host.lower()}/__ics/callback?code={code}"
    resp = RedirectResponse(target, status_code=302)
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@router.get("/{asset_id}")
async def get_app(
    asset_id: UUID, user: CurrentUser, session: Session, settings: AppSettings
) -> dict[str, Any]:
    require_enabled(settings)
    return await status_svc.detail(session, settings, user, asset_id)


@router.post("/{asset_id}/control")
async def control_app(
    asset_id: UUID,
    body: ControlRequest,
    response: Response,
    user: CurrentUser,
    session: Session,
    settings: AppSettings,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    require_enabled(settings)
    view, created = await control.control(
        session,
        settings,
        user,
        asset_id,
        action=body.action,
        expected_generation=body.expected_generation,
        idempotency_key=_key(body.idempotency_key, idempotency_key),
    )
    response.status_code = (
        status.HTTP_202_ACCEPTED if view["status"] == "running" else status.HTTP_200_OK
    )
    return {**view, "replayed": not created}


@router.get("/{asset_id}/logs")
async def app_logs(
    asset_id: UUID,
    user: CurrentUser,
    session: Session,
    settings: AppSettings,
    cursor: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    require_enabled(settings)
    return await status_svc.logs(session, user, asset_id, cursor=cursor, limit=limit)


@router.get("/{asset_id}/releases")
async def app_releases(
    asset_id: UUID, user: CurrentUser, session: Session, settings: AppSettings
) -> dict[str, Any]:
    require_enabled(settings)
    return await status_svc.releases(session, user, asset_id)


@router.get("/{asset_id}/package")
async def app_package(
    asset_id: UUID,
    user: CurrentUser,
    session: Session,
    settings: AppSettings,
    version: Annotated[int | None, Query(ge=1)] = None,
    path: Annotated[str | None, Query(max_length=200)] = None,
) -> dict[str, Any]:
    require_enabled(settings)
    return await status_svc.package(session, settings, user, asset_id, version=version, path=path)


@router.get("/{asset_id}/document")
async def get_document(
    asset_id: UUID,
    user: CurrentUser,
    session: Session,
    settings: AppSettings,
    collection: Annotated[str | None, Query(pattern=r"^[a-z][a-z0-9_]{0,47}$")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(max_length=400)] = None,
    overview: bool = True,
    lines: Annotated[str | None, Query(pattern=r"^\d+-\d+$")] = None,
    max_lines: Annotated[int | None, Query(ge=1, le=10_000)] = None,
    html: bool = True,
) -> dict[str, Any]:
    """The app as a document (Markdown and sanitized HTML): its own view,
    state, permissions, data model and the records the caller may list."""
    require_enabled(settings)
    return await document.render(
        session,
        settings,
        user,
        asset_id,
        collection=collection,
        limit=limit,
        cursor=cursor,
        overview=overview,
        lines=lines,
        max_lines=max_lines,
        html=html,
    )


@router.get("/{asset_id}/access")
async def get_access(
    asset_id: UUID, user: CurrentUser, session: Session, settings: AppSettings
) -> dict[str, Any]:
    """Who can open the app and with which permissions, plus what each
    permission of the active release unlocks."""
    require_enabled(settings)
    return await people.overview(session, settings, user, asset_id)


@router.put("/{asset_id}/access")
async def put_access(
    asset_id: UUID, body: AccessRequest, user: CurrentUser, session: Session, settings: AppSettings
) -> dict[str, Any]:
    """Set one person's or project's direct grants to exactly `roles` plus
    `permissions` (idempotent); `can_open` also adds or removes the person's
    viewer share."""
    require_enabled(settings)
    return await people.set_access(
        session,
        settings,
        user,
        asset_id,
        user_email=body.user_email,
        project_id=body.project_id,
        roles=body.roles,
        permissions=body.permissions,
        can_open=body.can_open,
    )


# ---------- private broker API ----------


async def require_service(
    settings: AppSettings,
    token: Annotated[str | None, Header(alias="X-ICS-Service-Token")] = None,
) -> None:
    expected = settings.microapps_service_token
    if (
        not settings.microapps_enabled
        or not expected
        or not token
        or not hmac.compare_digest(token, expected)
    ):
        raise ApiError(status.HTTP_404_NOT_FOUND, "not_found", "not found")


Service = Annotated[None, Depends(require_service)]


class AuthorizeRequest(BaseModel):
    asset: str = Field(min_length=32, max_length=32)
    environment: str = Field(pattern="^prod$")
    user_id: UUID | None = None
    share_id: UUID | None = None


class ExchangeRequest(BaseModel):
    code: str = Field(max_length=200)
    host: str = Field(max_length=200)
    state: str = Field(max_length=128)


class HostRequest(BaseModel):
    host: str = Field(max_length=200)


@internal_router.post("/authorize")
async def internal_authorize(
    body: AuthorizeRequest, _: Service, session: Session
) -> dict[str, Any]:
    return await runtime.authorize(
        session, body.asset, body.environment, body.user_id, body.share_id
    )


@internal_router.post("/hosts/resolve")
async def internal_resolve_host(
    body: HostRequest, _: Service, session: Session, settings: AppSettings
) -> dict[str, str]:
    """The app the broker serves on a short host: the label is random, so
    only this mapping, never the host text, says which app it is."""
    env = await hosts.env_for_host(session, settings, body.host)
    return {"host": body.host.lower(), "asset_hex": env.asset_hex, "environment": env.environment}


@internal_router.post("/launch/exchange")
async def internal_exchange(body: ExchangeRequest, _: Service) -> dict[str, Any]:
    return await runtime.exchange_launch_code(body.code, body.host, body.state)


@internal_router.get("/releases/{release_id}/bundle")
async def internal_bundle(
    release_id: UUID, _: Service, session: Session, settings: AppSettings
) -> dict[str, Any]:
    return await runtime.bundle(session, settings, release_id)


@internal_router.get("/releases/{release_id}/public")
async def internal_public(
    release_id: UUID,
    _: Service,
    session: Session,
    settings: AppSettings,
    path: Annotated[str, Query(max_length=300)],
) -> Response:
    data = await runtime.public_file(session, settings, release_id, path)
    if data is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "not_found", "not found")
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    return Response(content=data, media_type=mime)


@internal_router.get("/environments/{asset_id}/{environment}/binding")
async def internal_binding(
    asset_id: UUID, environment: str, _: Service, session: Session, settings: AppSettings
) -> dict[str, Any]:
    if environment != ENVIRONMENT:
        raise ApiError(status.HTTP_404_NOT_FOUND, "not_found", "not found")
    return await runtime.binding(session, settings, asset_id, environment)


@internal_router.post("/report")
async def internal_report(request: Request, _: Service, session: Session) -> dict[str, Any]:
    payload = await request.json()
    if not isinstance(payload, dict):
        raise ApiError(status.HTTP_400_BAD_REQUEST, "bad_report", "report must be an object")
    return await runtime.report(session, payload)
