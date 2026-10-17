"""Security report endpoint for html_bundle assets."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import permissions
from app.auth import CurrentUser
from app.bundle_scan import localize_report
from app.db import get_session
from app.errors import ApiError
from app.i18n import resolve_locale
from app.i18n.request import AcceptLanguage
from app.json_response import ORJSONResponse

from ._router import router


@router.get("/by-slug/{slug}/security")
async def asset_security(
    slug: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    accept_language: AcceptLanguage = None,
) -> ORJSONResponse:
    # editor+, like `include_security_report` in `/doc`: findings are a
    # review tool, not content for readers.
    asset, _ = await permissions.get_asset_with_role(
        session, user=user, min_role="editor", slug=slug
    )
    if asset.kind != "html_bundle":
        raise ApiError(
            status.HTTP_404_NOT_FOUND, "not_html_bundle", "security report only for html_bundle"
        )
    return ORJSONResponse(
        {
            "slug": asset.slug,
            "security_status": asset.security_status,
            "security_report": localize_report(
                asset.security_report,
                resolve_locale(user.locale, accept_language=accept_language),
            ),
            "security_bypass": asset.security_bypass,
            "security_bypass_at": asset.security_bypass_at.isoformat()
            if asset.security_bypass_at
            else None,
            "security_bypass_reason": asset.security_bypass_reason,
            "scanned_at": asset.updated_at.isoformat(),
        }
    )
