"""OAuth 2.1 Authorization Server endpoints under `/api/auth/oauth/*`.

RFC 8414/OIDC discovery, JWKS, RFC 6749 authorize/token/revoke, PKCE S256
only, RFC 8707 `resource` required, RFC 7591 DCR (public clients only).
Submodules register on `router` by side-effect import; `_verify_pkce` is
re-exported for tests.
"""

from __future__ import annotations

from . import authorize, me, metadata, register, revoke, token  # noqa: F401
from ._router import _verify_pkce, router
from .metadata import discovery_router

__all__ = ["_verify_pkce", "discovery_router", "router"]
