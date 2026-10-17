"""Doc type vocabulary (ADR-0015): `GET /api/doc-types` for signed-in users,
`GET/POST/PATCH /api/admin/doc-types` for admins. Types are archived, never
deleted."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.auth import AdminUser, CurrentUser
from app.db import get_session
from app.i18n import resolve_locale
from app.i18n.request import AcceptLanguage
from app.services import doc_types

router = APIRouter(prefix="/api/doc-types", tags=["doc-types"])
admin_router = APIRouter(prefix="/api/admin/doc-types", tags=["admin"])

_KEY = r"^[a-z][a-z0-9_]{1,31}$"


class DocTypeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=_KEY)
    label_pl: str = Field(min_length=1, max_length=100)
    label_en: str = Field(min_length=1, max_length=100)
    agent_hint: str | None = Field(default=None, max_length=500)
    default_review_days: int | None = Field(default=None, ge=1, le=3650)
    properties_schema: dict[str, Any] = Field(default_factory=dict)
    position: int = 0


class DocTypePatch(BaseModel):
    """Only the fields present change; `archived` sets or clears `archived_at`."""

    model_config = ConfigDict(extra="forbid")

    label_pl: str | None = Field(default=None, min_length=1, max_length=100)
    label_en: str | None = Field(default=None, min_length=1, max_length=100)
    agent_hint: str | None = Field(default=None, max_length=500)
    default_review_days: int | None = Field(default=None, ge=1, le=3650)
    properties_schema: dict[str, Any] | None = None
    position: int | None = None
    archived: bool | None = None


@router.get("")
async def list_doc_types(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    include_archived: bool = False,
    accept_language: AcceptLanguage = None,
) -> list[dict]:
    """Archived types are listed on request: assets keep them, so the UI
    still needs their labels."""
    locale = resolve_locale(user.locale, accept_language=accept_language)
    rows = await doc_types.list_doc_types(session, include_archived=include_archived)
    return [doc_types.doc_type_row(d, locale) for d in rows]


@admin_router.get("")
async def admin_list_doc_types(
    admin: AdminUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    accept_language: AcceptLanguage = None,
) -> list[dict]:
    """Every type, archived included, with both labels and `archived_at`."""
    locale = resolve_locale(admin.locale, accept_language=accept_language)
    rows = await doc_types.list_doc_types(session, include_archived=True)
    return [doc_types.doc_type_row(d, locale) for d in rows]


@admin_router.post("", status_code=status.HTTP_201_CREATED)
async def create_doc_type(
    body: DocTypeCreate,
    admin: AdminUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    request: Request,
    accept_language: AcceptLanguage = None,
) -> dict:
    doc_type = await doc_types.create_doc_type(session, body.model_dump())
    await audit.record_from_request(
        session,
        request,
        actor=admin,
        action="doc_type_created",
        target=f"doc_type:{doc_type.key}",
        payload={"key": doc_type.key},
    )
    await session.commit()
    return doc_types.doc_type_row(
        doc_type, resolve_locale(admin.locale, accept_language=accept_language)
    )


@admin_router.patch("/{key}")
async def update_doc_type(
    key: str,
    body: DocTypePatch,
    admin: AdminUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    request: Request,
    accept_language: AcceptLanguage = None,
) -> dict:
    changes = body.model_dump(exclude_unset=True)
    for name in ("label_pl", "label_en", "position", "archived"):
        # Columns without a null value: null leaves them as they are.
        if name in changes and changes[name] is None:
            del changes[name]
    doc_type, changed = await doc_types.update_doc_type(session, key, changes)
    if changed:
        await audit.record_from_request(
            session,
            request,
            actor=admin,
            action="doc_type_updated",
            target=f"doc_type:{doc_type.key}",
            payload={"key": doc_type.key, "fields": changed},
        )
        await session.commit()
    return doc_types.doc_type_row(
        doc_type, resolve_locale(admin.locale, accept_language=accept_language)
    )
