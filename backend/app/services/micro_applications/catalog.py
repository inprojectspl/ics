"""What an app's roles and permissions are, as the people who give access
see them: labels and descriptions from the manifest, and what each
permission unlocks, derived from its CRUD rules and endpoints."""

from __future__ import annotations

from typing import Any

from app.models import MicroAppRelease
from app.services.micro_applications import access

PLATFORM_DESCRIPTIONS = {
    "app.publish": ["publish new releases (ics_microapp_apply)"],
    "app.control": ["enable, suspend, sleep, restart; read logs"],
}


def role_catalog(release: MicroAppRelease | None) -> list[dict[str, Any]]:
    """The roles of the active release in the manifest's order."""
    return [
        {
            "role": name,
            "label": role["label"],
            "description": role.get("description"),
            "permissions": sorted(role["permissions"]),
        }
        for name, role in access.declared_roles(release).items()
    ]


def permission_catalog(release: MicroAppRelease | None) -> list[dict[str, Any]]:
    """Each permission of the active release with its label and what it
    unlocks, derived from the manifest, plus the platform permissions."""
    manifest: dict[str, Any] = release.manifest if release else {}
    declared: dict[str, dict[str, Any]] = manifest.get("permissions") or {}
    allows: dict[str, list[str]] = {p: [] for p in declared}
    collections = (manifest.get("database") or {}).get("collections") or {}
    for name, collection in collections.items():
        for op, rule in (collection.get("crud") or {}).items():
            scope = rule.get("rowScope", "all")
            where = "" if scope == "all" else f" ({scope} rows)"
            allows.setdefault(rule["permission"], []).append(f"{name}: {op}{where}")
    for ep in manifest.get("endpoints") or []:
        allows.setdefault(ep["permission"], []).append(
            f"{ep['method']} {ep['path']} ({ep['name']})"
        )
    items = [
        {
            "permission": p,
            "label": declared[p]["label"],
            "description": declared[p].get("description"),
            "platform": False,
            "allows": v,
        }
        for p, v in sorted(allows.items())
        if p in declared
    ]
    items += [
        {"permission": p, "label": None, "description": None, "platform": True, "allows": v}
        for p, v in PLATFORM_DESCRIPTIONS.items()
    ]
    return items
