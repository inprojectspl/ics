"""What changed in an app between two manifests, in the app's own terms:
roles, permissions, endpoints, capabilities, data model and settings.

The file diff of two package versions says which lines moved; this says
what that means for the people using the app (a role lost a permission, a
collection got a field). Plans show it against the active release, version
comparisons between any two package versions.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MicroAppRelease

# Top-level parts compared as a whole; `metadata` and `frontend` key by key.
_SETTINGS = ("runtime", "compatibility", "limitsRequested", "document")

Detail = Callable[[dict[str, Any], dict[str, Any]], str]


def _change(area: str, name: str, change: str, detail: str = "") -> dict[str, str]:
    return {"area": area, "name": name, "change": change, "detail": detail}


def _sets(old: set[str], new: set[str]) -> str:
    """`+a +b -c`: what a set gained and lost."""
    return " ".join([*(f"+{x}" for x in sorted(new - old)), *(f"-{x}" for x in sorted(old - new))])


def _differing_keys(before: dict[str, Any], after: dict[str, Any], keys: Any = None) -> str:
    names = keys if keys is not None else sorted(set(before) | set(after))
    return ", ".join(k for k in names if before.get(k) != after.get(k))


def _role(before: dict[str, Any], after: dict[str, Any]) -> str:
    perms = _sets(set(before.get("permissions", [])), set(after.get("permissions", [])))
    return " ".join(
        p for p in (perms, _differing_keys(before, after, ("label", "description"))) if p
    )


def _collection(before: dict[str, Any], after: dict[str, Any]) -> str:
    fb, fa = before.get("fields", {}), after.get("fields", {})
    fields = _sets(set(fb), set(fa))
    retyped = _differing_keys(fb, fa, sorted(set(fb) & set(fa)))
    parts = (
        fields and f"fields {fields}",
        retyped and f"changed {retyped}",
        _differing_keys(before, after, ("crud", "indexes")),
    )
    return "; ".join(p for p in parts if p)


def _keyed(
    area: str, old: dict[str, Any], new: dict[str, Any], detail: Detail
) -> list[dict[str, str]]:
    """Added, removed and changed entries of a name -> definition mapping."""
    out = [_change(area, n, "added") for n in sorted(set(new) - set(old))]
    out += [_change(area, n, "removed") for n in sorted(set(old) - set(new))]
    out += [
        _change(area, n, "changed", detail(old[n], new[n]))
        for n in sorted(set(old) & set(new))
        if old[n] != new[n]
    ]
    return out


def _areas(m: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Each area of a manifest as a name -> definition mapping."""
    return {
        "role": m.get("roles") or {},
        "permission": m.get("permissions") or {},
        "endpoint": {e["name"]: e for e in m.get("endpoints", [])},
        "capability": m.get("capabilities") or {},
        "collection": (m.get("database") or {}).get("collections") or {},
        "setting": {
            **{k: m[k] for k in _SETTINGS if k in m},
            **{k: m.get(k) or {} for k in ("metadata", "frontend")},
        },
    }


_DETAIL: dict[str, Detail] = {
    "role": _role,
    "collection": _collection,
    "setting": lambda b, a: _differing_keys(b, a) if isinstance(b, dict) else "",
}


def manifest_changes(old: dict[str, Any], new: dict[str, Any]) -> list[dict[str, str]]:
    """Changes from `old` to `new`, by area in a stable order: roles,
    permissions, endpoints, capabilities, collections, settings."""
    before, after = _areas(old), _areas(new)
    return [
        c
        for area in before
        for c in _keyed(area, before[area], after[area], _DETAIL.get(area, _differing_keys))
    ]


async def between_versions(
    session: AsyncSession, asset_id: UUID, from_v: int, to_v: int
) -> list[dict[str, str]] | None:
    """`manifest_changes` of two package versions, from the manifests their
    releases keep (every package version is a release); None when one of
    them has none."""
    rows = dict(
        (
            await session.execute(
                select(MicroAppRelease.package_version, MicroAppRelease.manifest).where(
                    MicroAppRelease.asset_id == asset_id,
                    MicroAppRelease.package_version.in_((from_v, to_v)),
                )
            )
        ).all()
    )
    if from_v not in rows or to_v not in rows:
        return None
    return manifest_changes(rows[from_v], rows[to_v])
