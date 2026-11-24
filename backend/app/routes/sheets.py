"""Google Sheets links of micro-applications (ADR-0031, ADR-0033).

`/api/integrations/google/*` connects the signed-in person's Google account
for Sheets; `/api/micro-applications/{id}/sheets/*` configures an app's link
to a spreadsheet file and its mappings of collections to tabs, and runs a sync: preview, apply with decisions, check an uncertain write.
The same endpoints serve the panel (cookie session) and ICS-MCP (bearer).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app import ratelimit
from app.auth import CurrentUser
from app.config import Settings, get_settings
from app.db import get_session
from app.domain_errors import DomainError
from app.errors import ApiError
from app.redis_client import get_redis
from app.services.sheets import google, grants, inspect, links, sync, views, write
from app.util import safe_return_path

router = APIRouter(tags=["sheets"])
Session = Annotated[AsyncSession, Depends(get_session)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def _require_enabled(settings: Settings) -> None:
    if not grants.enabled(settings):
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "google_sheets_disabled",
            "Google Sheets links are not configured on this ICS",
        )


# ------------------------------------------------------------ the account


@router.get("/api/integrations/google")
async def google_status(
    user: CurrentUser, session: Session, settings: AppSettings
) -> dict[str, Any]:
    grant = await grants.grant_of(session, user.id)
    return {
        "enabled": grants.enabled(settings),
        "connected": grant is not None,
        "email": grant.email if grant else None,
    }


@router.get("/api/integrations/google/connect")
async def google_connect(
    user: CurrentUser,
    settings: AppSettings,
    next_path: Annotated[str | None, Query(alias="next", max_length=2048)] = None,
) -> RedirectResponse:
    _require_enabled(settings)
    url = await grants.start(settings, user, safe_return_path(next_path) or "/")
    return RedirectResponse(url, status_code=302, headers={"Cache-Control": "no-store"})


def _with_param(path: str, key: str, value: str) -> str:
    sep = "&" if "?" in path else "?"
    return f"{path}{sep}{urlencode({key: value})}"


@router.get("/api/integrations/google/callback")
async def google_callback(
    user: CurrentUser,
    session: Session,
    settings: AppSettings,
    state: Annotated[str, Query(max_length=128)] = "",
    code: Annotated[str | None, Query(max_length=2048)] = None,
    error: Annotated[str | None, Query(max_length=128)] = None,
) -> RedirectResponse:
    """Back where the connection started, with `?google=connected` or the
    error code for the page to explain."""
    _require_enabled(settings)
    back = await grants.back_of(state)
    outcome = "connected"
    if error or not code:
        # Declined on the consent screen; drop the pending state.
        await grants.discard(state)
        outcome = "declined"
    else:
        try:
            await grants.finish(session, settings, user, state=state, code=code)
            await session.commit()
        except (google.GoogleError, DomainError) as e:
            outcome = e.code
    resp = RedirectResponse(_with_param(back, "google", outcome), status_code=302)
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


@router.delete("/api/integrations/google")
async def google_disconnect(
    user: CurrentUser, session: Session, settings: AppSettings
) -> dict[str, Any]:
    return {"disconnected": await grants.disconnect(session, settings, user)}


# A tab, by its Google id or its name.
TabRef = int | Annotated[str, Field(max_length=100)]


class InspectIn(BaseModel):
    spreadsheet: str = Field(max_length=500, description="Spreadsheet URL or id")
    tab: TabRef | None = Field(
        default=None, description="The tab to sample: its name or id; the first tab by default"
    )


async def _sync_gate(user: CurrentUser, settings: AppSettings) -> None:
    """Every sync step reads the whole sheet: on only when configured, and
    rate limited per person."""
    _require_enabled(settings)
    await ratelimit.enforce(get_redis(), ratelimit.SHEETS_SYNC, str(user.id))


SyncGate = Annotated[None, Depends(_sync_gate)]


@router.post("/api/integrations/google/inspect")
async def google_inspect(
    body: InspectIn, _: SyncGate, user: CurrentUser, session: Session, settings: AppSettings
) -> dict[str, Any]:
    """Tabs, headers and suggested field types of a spreadsheet, read with the
    caller's own Google account, to design an app around it."""
    return await inspect.inspect(session, settings, user, body.spreadsheet, body.tab)


# ------------------------------------------------------------- the link

_APP = "/api/micro-applications/{asset_id}/sheets"


class ColumnIn(BaseModel):
    field: str = Field(max_length=64)
    header: str = Field(max_length=100)
    owner: Literal["sheet", "app", "both"]


class MappingIn(BaseModel):
    collection: str = Field(max_length=64)
    tabs: list[TabRef] = Field(
        min_length=1,
        max_length=50,
        description="The tabs whose rows are this collection's records: names or ids",
    )
    append_to: TabRef | None = Field(
        default=None, description="With several tabs, the one new records are appended to"
    )
    columns: list[ColumnIn] = Field(max_length=200)
    key_field: str | None = Field(
        default=None,
        max_length=64,
        description="A linked field unique across the tabs that matches rows to records; "
        "required with several tabs",
    )
    tab_field: str | None = Field(
        default=None, max_length=64, description="A string field that takes the row's tab name"
    )


class LinkIn(BaseModel):
    spreadsheet: str = Field(max_length=500, description="Spreadsheet URL or id")
    mappings: list[MappingIn] | None = Field(default=None, max_length=20)
    # One collection on one tab, as ICS-MCP before ADR-0033 (plugin 3.8.0)
    # sends it; drop once those plugins are gone.
    collection: str | None = Field(default=None, max_length=64)
    sheet_title: str | None = Field(default=None, max_length=100)
    columns: list[ColumnIn] | None = Field(default=None, max_length=200)
    key_field: str | None = Field(default=None, max_length=64)
    account_mode: Literal["owner_account", "per_user"]
    paused: bool = False
    auto_sync: bool = Field(
        default=False,
        description="Sync on its own, as the owner: app changes within seconds, "
        "sheet edits every few minutes; conflicts wait for a person",
    )
    expected_revision: int | None = None
    reset_base: bool = False

    def as_body(self) -> dict[str, Any]:
        body = self.model_dump(exclude={"collection", "sheet_title", "columns", "key_field"})
        if self.mappings is None:
            if self.collection is None or self.sheet_title is None or self.columns is None:
                raise ApiError(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "mappings_invalid",
                    "link the collections in `mappings`",
                )
            body["mappings"] = [
                {
                    "collection": self.collection,
                    "tabs": [self.sheet_title],
                    "columns": [c.model_dump() for c in self.columns],
                    "key_field": self.key_field,
                }
            ]
        return body


class ApplyIn(BaseModel):
    decisions: dict[str, Literal["app", "sheet"]] = Field(default_factory=dict)


@router.get(_APP)
async def sheet_status(
    asset_id: UUID, user: CurrentUser, session: Session, settings: AppSettings
) -> dict[str, Any]:
    return await views.status(session, settings, user, asset_id)


@router.put(_APP)
async def sheet_save(
    asset_id: UUID, body: LinkIn, user: CurrentUser, session: Session, settings: AppSettings
) -> dict[str, Any]:
    _require_enabled(settings)
    link, mappings = await links.save(session, user, asset_id, body.as_body())
    await session.commit()
    return links.view(link, mappings)


@router.delete(_APP, status_code=status.HTTP_204_NO_CONTENT)
async def sheet_remove(
    asset_id: UUID, user: CurrentUser, session: Session, settings: AppSettings
) -> None:
    await links.remove(session, user, asset_id)
    await session.commit()


@router.post(f"{_APP}/preview", status_code=status.HTTP_201_CREATED)
async def sheet_preview(
    asset_id: UUID, _: SyncGate, user: CurrentUser, session: Session, settings: AppSettings
) -> dict[str, Any]:
    op = await sync.preview(session, settings, user, asset_id)
    return views.op_view(op, user)


@router.get(f"{_APP}/operations/{{op_id}}")
async def sheet_operation(
    asset_id: UUID, op_id: UUID, user: CurrentUser, session: Session
) -> dict[str, Any]:
    return await views.get_operation(session, user, asset_id, op_id)


@router.post(f"{_APP}/operations/{{op_id}}/apply")
async def sheet_apply(
    asset_id: UUID,
    op_id: UUID,
    body: ApplyIn,
    _: SyncGate,
    user: CurrentUser,
    session: Session,
    settings: AppSettings,
) -> dict[str, Any]:
    op = await sync.apply(session, settings, user, asset_id, op_id, body.decisions)
    return views.op_view(op, user)


@router.post(f"{_APP}/operations/{{op_id}}/check")
async def sheet_check(
    asset_id: UUID,
    op_id: UUID,
    _: SyncGate,
    user: CurrentUser,
    session: Session,
    settings: AppSettings,
) -> dict[str, Any]:
    op = await write.check(session, settings, user, asset_id, op_id)
    return views.op_view(op, user)


@router.post(f"{_APP}/request-access")
async def sheet_request_access(
    asset_id: UUID, user: CurrentUser, session: Session, settings: AppSettings
) -> dict[str, Any]:
    _require_enabled(settings)
    return await views.request_access(session, settings, user, asset_id)
