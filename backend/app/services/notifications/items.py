"""Entry payloads: building them at fan-out and turning them into the API shape.

An entry keeps codes and parameters, never text (ADR-0011): the frontend
renders it in the reader's language, and e-mail, Chat and push render it in
the recipient's language on the backend (`render.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, get_args

from .inbox import Entry

NotificationCode = Literal[
    "asset.created",
    "asset.added",
    "asset.updated",
    "asset.deleted",
    "channel.chat_disabled",
]
EventKind = Literal["asset.created", "asset.added", "asset.updated", "asset.deleted"]
EVENT_KINDS: tuple[EventKind, ...] = get_args(EventKind)


@dataclass(frozen=True, slots=True)
class AssetRef:
    id: str
    slug: str
    title: str
    kind: str


@dataclass(frozen=True, slots=True)
class ProjectRef:
    slug: str
    name: str


def build_payload(
    code: NotificationCode,
    *,
    asset: AssetRef | None,
    project: ProjectRef | None,
    actor_id: str | None,
    actor_name: str | None,
    actor_count: int = 1,
    version: int | None = None,
    from_version: int | None = None,
    count: int = 1,
    params: dict[str, str | int] | None = None,
) -> dict[str, Any]:
    """Compact keys: the payload is stored once per recipient."""
    p: dict[str, Any] = {"c": code, "n": count}
    if asset is not None:
        p.update({"as": asset.id, "sl": asset.slug, "t": asset.title, "k": asset.kind})
    if project is not None:
        p.update({"ps": project.slug, "pn": project.name})
    if actor_id is not None:
        p.update({"ai": actor_id, "an": actor_name or ""})
        if actor_count > 1:
            # `an` then lists several people; the sentence needs the plural.
            p["na"] = actor_count
    if version is not None:
        p["v"] = version
    if from_version is not None and from_version != version:
        p["fv"] = from_version
    if params:
        p["x"] = params
    return p


def entry_time(entry_id: str) -> datetime:
    return datetime.fromtimestamp(int(entry_id.split("-", 1)[0]) / 1000, tz=UTC)


def link_of(payload: dict[str, Any]) -> str | None:
    """App-relative URL the entry opens. Several new versions open the diff
    from the last version the reader knew to the newest."""
    code = payload.get("c")
    slug = payload.get("sl")
    if code == "channel.chat_disabled":
        return "/account/notifications"
    if code == "asset.deleted":
        return f"/projects/{payload['ps']}" if payload.get("ps") else None
    if not slug:
        return None
    version, first = payload.get("v"), payload.get("fv")
    if (
        code == "asset.updated"
        and isinstance(version, int)
        and isinstance(first, int)
        and 1 < first <= version
    ):
        return f"/v/{slug}/diff?from={first - 1}&to={version}"
    return f"/v/{slug}"


def to_item(entry: Entry, *, unavailable: bool = False) -> dict[str, Any]:
    p = entry.payload
    asset = None
    if p.get("as") and not unavailable:
        asset = {"id": p["as"], "slug": p["sl"], "title": p.get("t") or "", "kind": p.get("k")}
    project = None
    if p.get("ps") and not unavailable:
        project = {"slug": p["ps"], "name": p.get("pn") or ""}
    actor = {"id": p["ai"], "name": p.get("an") or ""} if p.get("ai") else None
    return {
        "id": entry.id,
        "code": p.get("c"),
        "at": entry_time(entry.id).isoformat(),
        "read": entry.read,
        "unavailable": unavailable,
        "actor": actor,
        "asset": asset,
        "project": project,
        "version": p.get("v"),
        "from_version": p.get("fv"),
        "count": int(p.get("n") or 1),
        "link": None if unavailable else link_of(p),
        "params": p.get("x") or {},
    }
