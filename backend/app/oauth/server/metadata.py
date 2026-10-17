"""RFC 8414 + OpenID Discovery + JWKS endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from fastapi.responses import JSONResponse

from app.config import Settings, get_settings
from app.oauth import keys as keys_mod
from app.oauth import scopes as scopes_mod

from ._router import _issuer, router


def _as_metadata_dict(settings: Settings) -> dict:
    iss = _issuer(settings)
    return {
        "issuer": iss,
        "authorization_endpoint": f"{iss}/api/auth/oauth/authorize",
        "token_endpoint": f"{iss}/api/auth/oauth/token",
        "revocation_endpoint": f"{iss}/api/auth/oauth/revoke",
        "registration_endpoint": f"{iss}/api/auth/oauth/register",
        "jwks_uri": f"{iss}/api/auth/oauth/jwks.json",
        "scopes_supported": sorted(scopes_mod.ALL_SUPPORTED),
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_basic"],
        "service_documentation": f"{iss}/api/auth/oauth/docs",
    }


@router.get("/.well-known/oauth-authorization-server")
async def authorization_server_metadata(
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    return JSONResponse(_as_metadata_dict(settings))


@router.get("/.well-known/openid-configuration")
async def oidc_metadata(
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    data = _as_metadata_dict(settings)
    iss = _issuer(settings)
    data["subject_types_supported"] = ["public"]
    data["id_token_signing_alg_values_supported"] = ["RS256"]
    data["userinfo_endpoint"] = f"{iss}/api/auth/oauth/me"
    return JSONResponse(data)


@router.get("/jwks.json")
async def jwks(settings: Annotated[Settings, Depends(get_settings)]) -> JSONResponse:
    return JSONResponse(keys_mod.jwks_document(settings))
