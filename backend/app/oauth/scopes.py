"""OAuth scopes for MCP. OAuth clients get the flat `ics` scope; the
granular names (`ics:read`, `ics:write`, `ics:share`, `ics:delete`) are
reserved for step-up consent via `WWW-Authenticate: ... error=insufficient_scope`."""

from __future__ import annotations

# Flat scope that grants all user-level operations. Tools that would
# normally require granular scopes are gated by ICS RBAC (Asset.effective_role).
FLAT_SCOPE = "ics"

# Reserved names for future granular scopes, declared so consent UI / DCR
# can validate them, but not enforced on resource access yet.
GRANULAR_SCOPES = frozenset(
    {
        "ics:read",
        "ics:write",
        "ics:share",
        "ics:delete",
        "ics:projects:read",
    }
)

ALL_SUPPORTED = frozenset({FLAT_SCOPE}) | GRANULAR_SCOPES


def normalize_scope_string(s: str) -> list[str]:
    """Split space-separated scope value, drop empties, preserve order."""
    return [tok for tok in s.split() if tok]


def validate_scopes(requested: list[str], allowed: list[str]) -> list[str]:
    """Return the intersection in request order. Empty result is the caller's problem."""
    allowed_set = set(allowed)
    return [s for s in requested if s in allowed_set]
