"""Auth endpoints: login, logout, password reset, invite/setup, register/verify, Google OIDC.

All under `/api/auth/*`. The package exports a shared `router`;
submodules register their endpoints through side-effect imports.
"""

from __future__ import annotations

from . import google, invite, login, me, password_reset, register, tokens  # noqa: F401
from ._router import router

__all__ = ["router"]
