"""Owner-facing CRUD: create share link, list shares, revoke share."""

from __future__ import annotations

import asyncio
from typing import Annotated
from uuid import UUID

from fastapi import Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, email_templates, passwords, permissions, tokens
from app.auth import CurrentUser
from app.config import Settings, get_settings
from app.constants import MICRO_APPLICATION, SHARE_MODES
from app.db import get_session
from app.email_outbox import queue_email
from app.errors import ApiError
from app.i18n import resolve_locale
from app.i18n.request import AcceptLanguage
from app.models import Asset, ShareLink, User
from app.services import asset_security
from app.services import sharing as sharing_svc
from app.slug import generate_token

from ._models import CreateShareIn, ShareOut
from ._router import router
from ._shared import _magic_payload, _to_out


@router.post(
    "/api/assets/{asset_id}/shares",
    status_code=status.HTTP_201_CREATED,
)
async def create_share(
    asset_id: UUID,
    body: CreateShareIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    accept_language: AcceptLanguage = None,
) -> ShareOut:
    asset, _role = await permissions.get_shareable_asset(session, asset_id, user)
    if body.mode not in SHARE_MODES:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "unsupported_share_mode",
            f"share mode '{body.mode}' is not supported",
        )
    # Critical bundles can't be shared until an admin reviews the security scan
    # findings and grants a bypass. Admin's own share attempts don't get a
    # silent pass: the audit trail must show the deliberate bypass step.
    if asset_security.publication_blocked(asset):
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            "asset_critical",
            "asset flagged critical: administrator approval is required before sharing",
        )

    app_permissions = await _app_permissions_for(
        session, user, asset, body.app_roles, body.app_permissions
    )

    password_hash: str | None = None
    if body.mode == "password":
        if not body.password:
            raise ApiError(
                status.HTTP_400_BAD_REQUEST,
                "password_required",
                "password mode requires a password",
            )
        try:
            passwords.validate_password(body.password)
        except passwords.WeakPasswordError as e:
            raise ApiError(status.HTTP_400_BAD_REQUEST, "weak_password", str(e)) from e
        password_hash = await asyncio.to_thread(passwords.hash_password, body.password)

    allowed_emails = [e.lower() for e in body.allowed_emails] if body.allowed_emails else None
    if body.mode == "magic_email" and not allowed_emails:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "allowed_emails_required",
            "magic_email mode requires a list of addresses (allowed_emails)",
        )

    share = ShareLink(
        asset_id=asset.id,
        token=generate_token(),
        mode=body.mode,
        password_hash=password_hash,
        allowed_emails=allowed_emails,
        expires_at=body.expires_at,
        max_views=body.max_views,
        created_by=user.id,
        app_permissions=app_permissions,
    )
    session.add(share)
    await session.flush()

    if body.mode == "magic_email" and allowed_emails:
        # Recipients with an account get their own language; external
        # addresses get the sharer's.
        recipient_locales = dict(
            (
                await session.execute(
                    select(User.email, User.locale).where(User.email.in_(allowed_emails))
                )
            )
            .tuples()
            .all()
        )
        for addr in allowed_emails:
            magic = tokens.issue("magic_link", _magic_payload(share.id, addr))
            link = sharing_svc.build_share_url(settings, share.token, magic=magic)
            subj, txt, html = email_templates.magic_link(
                owner_email=user.email,
                asset_title=asset.title or asset.slug,
                share_url=link,
                locale=resolve_locale(
                    recipient_locales.get(addr), user.locale, accept_language=accept_language
                ),
            )
            await queue_email(
                session,
                to_email=addr,
                subject=subj,
                body=txt,
                body_html=html,
                purpose="magic_link",
            )

    await audit.record(
        session,
        actor=user,
        action="share_created",
        target=f"share:{share.id}",
        payload={
            "asset_id": str(asset.id),
            "mode": share.mode,
            "has_password": password_hash is not None,
            "magic_recipients": len(allowed_emails)
            if (body.mode == "magic_email" and allowed_emails)
            else 0,
            "expires_at": share.expires_at.isoformat() if share.expires_at else None,
            "app_permissions": app_permissions,
        },
    )
    await session.commit()
    await session.refresh(share)
    return _to_out(share, settings)


async def _app_permissions_for(
    session: AsyncSession,
    user: User,
    asset: Asset,
    roles: list[str] | None,
    requested: list[str] | None,
) -> list[str] | None:
    """A micro-application link must name what it grants: roles the active
    release defines and/or permissions it declares, stored together (roles as
    `role:<name>`). Only someone who may manage the app's access can hand
    them out. Documents take none."""
    if asset.kind != MICRO_APPLICATION:
        if requested or roles:
            raise ApiError(
                status.HTTP_400_BAD_REQUEST,
                "app_permissions_not_applicable",
                "app_permissions apply to micro-application links only",
            )
        return None
    from app.routes.micro_applications import require_enabled
    from app.services.micro_applications import access
    from app.services.micro_applications.common import load_app

    require_enabled(get_settings())
    _, env = await load_app(session, asset.id)
    if not (await access.rights(session, user, asset)).manage:
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            "manage_permission_required",
            "app.access.manage is required to share a micro-application",
        )
    release = await access.active_release(session, env)
    allowed = access.declared_permissions(release)
    defined = access.declared_roles(release)
    chosen = set(requested or [])
    chosen_roles = set(roles or [])
    if not (chosen or chosen_roles) or not chosen <= allowed or not chosen_roles <= defined.keys():
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "app_permissions_invalid",
            "name one or more roles the application defines or permissions it declares",
            extra={"allowed": sorted(allowed), "allowed_roles": list(defined)},
        )
    return sorted({access.role_grant(r) for r in chosen_roles} | chosen)


@router.get("/api/assets/{asset_id}/shares")
async def list_shares(
    asset_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[ShareOut]:
    await permissions.get_shareable_asset(session, asset_id, user)
    result = await session.execute(
        select(ShareLink)
        .where(ShareLink.asset_id == asset_id)
        .order_by(ShareLink.created_at.desc())
    )
    return [_to_out(s, settings) for s in result.scalars().all()]


@router.delete("/api/shares/{share_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_share(
    share_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    share = await session.get(ShareLink, share_id)
    if share is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "share_not_found", "share not found")
    # Resolve assertion via get_shareable_asset, which propagates 404 (gone)
    # and 403 (read-only collaborator) idiomatically.
    await permissions.get_shareable_asset(session, share.asset_id, user)
    try:
        await sharing_svc.revoke_share_link(session, share_id=share_id, actor=user)
    except sharing_svc.ShareNotFoundError as e:
        raise ApiError(status.HTTP_404_NOT_FOUND, "share_not_found", "share not found") from e
    await session.commit()
