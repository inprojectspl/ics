"""Sort order shared by every asset listing; the frontend mirrors it in
`lib/assetSort.ts`. Pins do not reorder. Ties break on the last content change
(`content_updated_at`, so tag or rename writes do not reorder), then
`Asset.id`, so paged results never overlap.
"""

from __future__ import annotations

from typing import Any, Literal

from sqlalchemy import ColumnElement, func

from app.models import Asset

AssetSortKey = Literal["updated", "created", "title", "versions", "kind"]
SortOrder = Literal["asc", "desc"]

# Direction used when the client picks a key without an explicit order:
# the natural reading of each key (newest, A-Z, most versions first).
DEFAULT_ORDER: dict[AssetSortKey, SortOrder] = {
    "updated": "desc",
    "created": "desc",
    "title": "asc",
    "versions": "desc",
    "kind": "asc",
}

# The column is backfilled and set on every insert; the fallback only guards
# rows written outside the ORM.
_LAST_CHANGE = func.coalesce(Asset.content_updated_at, Asset.updated_at)

_SORT_COLUMN: dict[AssetSortKey, Any] = {
    "updated": _LAST_CHANGE,
    "created": Asset.created_at,
    "title": func.lower(func.coalesce(Asset.title, Asset.slug)),
    "versions": Asset.version,
    "kind": Asset.kind,
}


def asset_order_by(
    sort: AssetSortKey = "updated", order: SortOrder | None = None
) -> list[ColumnElement]:
    """ORDER BY clauses for a query that selects `Asset`."""
    direction = order or DEFAULT_ORDER[sort]
    col, row_id = _SORT_COLUMN[sort], Asset.id
    keys = [col.asc(), row_id.asc()] if direction == "asc" else [col.desc(), row_id.desc()]
    return [keys[0], _LAST_CHANGE.desc(), keys[1]]
