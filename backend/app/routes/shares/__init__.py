"""ShareLink CRUD and the token-based viewer.

Modes: `org_sso` (allowed-domain account), `password` (verified state kept in
the session), `public`, `magic_email` (signed per-recipient link). Private
helpers are re-exported for tests.
"""

from __future__ import annotations

from . import auth, owner, resolve, viewer  # noqa: F401
from ._router import router
from ._shared import _magic_payload, _parse_magic_payload, _resolve_share

__all__ = [
    "_magic_payload",
    "_parse_magic_payload",
    "_resolve_share",
    "router",
]
