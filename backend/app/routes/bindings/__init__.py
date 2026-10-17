"""GitLab bindings: CRUD and signed sync.

A binding pairs an asset with an Ed25519 public key; the private key exists
only in the GitLab CI job, and sync accepts pushes signed with it.
"""

from __future__ import annotations

# Side-effect imports: submodules register endpoints on the shared router.
from . import crud, sync  # noqa: F401
from ._router import router

__all__ = ["router"]
