"""Projects: asset containers with per-user membership.

Invariant: exactly one owner per project (partial unique index); the owner
cannot be kicked, demoted or leave before transferring ownership. Handlers
and DTOs are re-exported for tests.
"""

from __future__ import annotations

# Side-effect imports: submodules register endpoints on the shared router.
from . import crud, hygiene, membership, watch  # noqa: F401
from ._models import (
    AcceptInviteIn,
    CreateProjectIn,
    InviteMemberIn,
    PatchMemberIn,
    PatchProjectIn,
    TransferOwnerIn,
)
from ._router import router
from .crud import (
    create_project,
    delete_project,
    get_project,
    list_projects,
    patch_project,
)
from .membership import (
    accept_invite,
    invite_member,
    kick_member,
    leave_project,
    patch_member,
    transfer_owner,
)

__all__ = [  # noqa: RUF022 - semantic order (router, DTOs, handlers)
    "router",
    # DTO models (used by tests to build request bodies)
    "AcceptInviteIn",
    "CreateProjectIn",
    "InviteMemberIn",
    "PatchMemberIn",
    "PatchProjectIn",
    "TransferOwnerIn",
    # CRUD handlers
    "create_project",
    "delete_project",
    "get_project",
    "list_projects",
    "patch_project",
    # Membership handlers
    "accept_invite",
    "invite_member",
    "kick_member",
    "leave_project",
    "patch_member",
    "transfer_owner",
]
