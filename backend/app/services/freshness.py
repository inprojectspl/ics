"""Document freshness, computed at projection time for the viewer at hand
(ADR-0015, section 4); there is no stored status to keep in sync.
`freshness_filter` is the SQL form of the same rules.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Literal, Protocol

from sqlalchemy import ColumnElement, and_, false, or_

from app.models import Asset

Freshness = Literal["superseded", "review_overdue", "current"]
# Every value is filterable; `superseded` needs the viewer's successor
# predicate, which the caller passes to `freshness_filter`.
FilterableFreshness = Freshness
Flag = Literal["summary_stale", "basis_changed"]


class _Dated(Protocol):
    review_due_at: datetime | None


class _Versioned(Protocol):
    version: int
    summary_version: int | None


def freshness(asset: _Dated, now: datetime, *, superseded: bool = False) -> Freshness:
    """First matching rule wins. `superseded` means a successor visible to
    the viewer exists (ADR-0016); the caller decides it only after the
    visibility check, so a hidden successor never marks the document
    superseded."""
    if superseded:
        return "superseded"
    if asset.review_due_at is not None and asset.review_due_at < now:
        return "review_overdue"
    return "current"


def flags(asset: _Versioned, *, summary: str | None, basis_changed: bool = False) -> list[Flag]:
    """Flags next to `freshness`; they do not exclude it. `summary` is passed
    in because the column is deferred and callers load it in one batch."""
    out: list[Flag] = []
    if summary and asset.summary_version is not None and asset.summary_version < asset.version:
        out.append("summary_stale")
    if basis_changed:
        out.append("basis_changed")
    return out


def freshness_filter(
    values: Iterable[FilterableFreshness], now: datetime, *, superseded: ColumnElement[bool]
) -> ColumnElement[bool]:
    """Assets whose freshness is one of `values` (OR), with the precedence
    of `freshness`: a superseded document is neither `review_overdue` nor
    `current`. `superseded` is the SQL form of "a successor visible to the
    viewer exists" (`graph_signals.visible_successor_exists`)."""
    overdue = Asset.review_due_at < now
    not_overdue = or_(Asset.review_due_at.is_(None), Asset.review_due_at >= now)
    wanted = set(values)
    clauses = []
    if "superseded" in wanted:
        clauses.append(superseded)
    if "review_overdue" in wanted:
        clauses.append(and_(overdue, ~superseded))
    if "current" in wanted:
        clauses.append(and_(not_overdue, ~superseded))
    return or_(*clauses) if clauses else false()
