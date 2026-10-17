"""Notifications API (ADR-0023, contract in `docs/notifications-api.md`).

Watch endpoints of a single asset or project live with those resources.
"""

from __future__ import annotations

# Side-effect imports: submodules register endpoints on the shared router.
from . import (  # noqa: F401
    inbox,
    settings,
    stream,
)
from ._router import router, watches_router

__all__ = ["router", "watches_router"]
