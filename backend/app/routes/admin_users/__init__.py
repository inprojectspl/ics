"""Admin user management API for the `/admin/users` panel.

Email is not editable (it is the identity key audit trails reference), and
admins never set passwords, only trigger the reset email. Deleting an
account cascades to its assets.
"""

from __future__ import annotations

from . import invitations, listing, permissions, tokens  # noqa: F401
from ._models import InviteIn, LockIn, PatchUserIn
from ._router import router
from .invitations import admin_password_reset, invite_user, reinvite
from .listing import list_users
from .permissions import delete_user, lock_user, patch_user, unlock_user

__all__ = [  # noqa: RUF022 - semantic order (router, DTOs, handlers)
    "router",
    # DTO
    "InviteIn",
    "LockIn",
    "PatchUserIn",
    # Listing
    "list_users",
    # Invitations / email flows
    "admin_password_reset",
    "invite_user",
    "reinvite",
    # Permissions / state
    "delete_user",
    "lock_user",
    "patch_user",
    "unlock_user",
]
