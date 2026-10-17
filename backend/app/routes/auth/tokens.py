"""Personal access tokens of the caller: `/api/auth/tokens` (ADR-0020)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app import email_templates
from app.auth import CurrentUser
from app.config import Settings, get_settings
from app.db import get_session
from app.email_outbox import queue_email
from app.errors import ApiError
from app.i18n import resolve_locale
from app.i18n.request import AcceptLanguage
from app.models import PersonalAccessToken
from app.services import pat

from ._router import router


class TokenCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    expires_at: datetime


def token_row(token: PersonalAccessToken) -> dict:
    return {
        "id": str(token.id),
        "name": token.name,
        "prefix": token.token_prefix,
        "scopes": list(token.scopes),
        "expires_at": token.expires_at.isoformat(),
        "last_used_at": token.last_used_at.isoformat() if token.last_used_at else None,
        "created_at": token.created_at.isoformat() if token.created_at else None,
    }


@router.get("/tokens")
async def list_tokens(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    tokens = await pat.list_for_user(session, user.id)
    return {"items": [token_row(t) for t in tokens]}


@router.post("/tokens", status_code=status.HTTP_201_CREATED)
async def create_token(
    body: TokenCreateIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    accept_language: AcceptLanguage = None,
) -> dict:
    """The plaintext `token` is in this response only; it is not stored. The
    owner gets a notice by e-mail, so a token created by someone else with
    access to the session does not go unnoticed."""
    token, plaintext = await pat.create(
        session, user=user, name=body.name, expires_at=body.expires_at
    )
    subject, text, html = email_templates.token_created(
        token_name=token.name,
        token_prefix=token.token_prefix,
        expires_on=token.expires_at.date().isoformat(),
        tokens_url=f"{settings.base_url}/account/tokens",
        locale=resolve_locale(user.locale, accept_language=accept_language),
    )
    await queue_email(
        session,
        to_email=user.email,
        subject=subject,
        body=text,
        body_html=html,
        purpose="notification",
        settings=settings,
    )
    await session.commit()
    await session.refresh(token)
    return {**token_row(token), "token": plaintext}


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(
    token_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    token = await pat.revoke(session, token_id=token_id, user_id=user.id, actor=user)
    if token is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "pat_not_found", "token not found")
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
