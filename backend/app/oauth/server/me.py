"""`/me` userinfo endpoint; works with both cookie session and bearer token."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from app.auth import get_current_user
from app.models import User

from ._router import router


@router.get("/me")
async def whoami(
    user: Annotated[User, Depends(get_current_user)],
    request: Request,
) -> JSONResponse:
    return JSONResponse(
        {
            "user_id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
            "role": user.role,
            "scopes": getattr(request.state, "oauth_scopes", []) or ["session"],
            "client_id": getattr(request.state, "oauth_client_id_external", None),
            "transport": getattr(request.state, "oauth_transport", "cookie"),
            "audience": getattr(request.state, "oauth_audience", None),
        }
    )
