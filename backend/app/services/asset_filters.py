"""Document scopes and faceted filters, applied before counting or paging."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Literal
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    String,
    and_,
    cast,
    func,
    literal,
    or_,
    select,
    true,
    union_all,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app import permissions
from app.domain_errors import InvalidInputError
from app.models import (
    Asset,
    AssetPin,
    AssetProjectShare,
    GitLabBinding,
    ProjectMember,
    ShareLink,
    User,
)
from app.services import graph_signals
from app.services.freshness import freshness_filter
from app.services.project_shares import in_project_filter
from app.util import now as utc_now

AssetScope = Literal["all", "state:mine", "state:shared-with-me", "state:pinned", "admin:review"]
Clauses = dict[str, ColumnElement[bool]]


def scope_predicates(user: User) -> Clauses:
    return {
        "all": true(),
        "state:mine": Asset.owner_id == user.id,
        "state:shared-with-me": and_(
            Asset.owner_id != user.id, permissions.shared_with_user_filter(user)
        ),
        "state:pinned": select(AssetPin.asset_id)
        .where(AssetPin.for_user(user.id))
        .correlate(Asset)
        .exists(),
        "admin:review": and_(Asset.security_status == "critical", ~Asset.security_bypass),
    }


def _share_mode(mode: str | None = None):
    stmt = select(ShareLink.id).where(
        ShareLink.asset_id == Asset.id, ShareLink.revoked_at.is_(None)
    )
    if mode:
        stmt = stmt.where(ShareLink.mode == mode)
    return stmt.exists()


def fixed_filter_predicates(user: User) -> Clauses:
    bound = select(GitLabBinding.id).where(GitLabBinding.asset_id == Asset.id).exists()
    superseded = graph_signals.visible_successor_exists(user, Asset.id)
    now = utc_now()
    return {
        "state:public": _share_mode("public"),
        "state:password": _share_mode("password"),
        "state:unshared": ~_share_mode(),
        "source:gitlab": bound,
        "source:manual": ~bound,
        **{
            f"fresh:{value}": freshness_filter([value], now, superseded=superseded)
            for value in ("current", "review_overdue", "superseded")
        },
    }


def filter_predicates(values: Sequence[str], fixed: Clauses) -> Clauses:
    """OR inside a group, AND between groups, matching the filter menu."""
    groups: dict[str, list[str]] = defaultdict(list)
    for value in values:
        kind, sep, term = value.partition(":")
        if (
            not sep
            or not term
            or kind not in {"type", "state", "source", "project", "doctype", "fresh", "tag"}
        ):
            raise InvalidInputError("validation_error", "Invalid document filter")
        groups[kind].append(term)
    predicates: Clauses = {}
    for kind, terms in groups.items():
        if kind in {"state", "source", "fresh"}:
            if any(f"{kind}:{term}" not in fixed for term in terms):
                raise InvalidInputError("validation_error", "Invalid document filter value")
            predicates[kind] = or_(*(fixed[f"{kind}:{term}"] for term in terms))
        elif kind == "type":
            predicates[kind] = Asset.kind.in_(terms)
        elif kind == "doctype":
            predicates[kind] = Asset.doc_type.in_(terms)
        elif kind == "tag":
            predicates[kind] = Asset.tags.overlap(terms)
        else:
            try:
                ids = [UUID(term) for term in terms]
            except ValueError:
                raise InvalidInputError("validation_error", "Invalid project filter") from None
            predicates[kind] = or_(*(in_project_filter(pid) for pid in ids))
    return predicates


async def facet_counts(
    session: AsyncSession,
    user: User,
    base: Sequence[ColumnElement[bool]],
    scope: AssetScope,
    groups: Clauses,
    fixed: Clauses,
) -> dict:
    """Counts over the authorized matching corpus, independent of LIMIT.

    Disjunctive facets omit their own group's constraint, so another value
    in that group remains selectable. All aggregates run in one round trip.
    """
    scopes = scope_predicates(user)
    scope_columns = {key: f"scope_{i}" for i, key in enumerate(scopes)}
    fixed_columns = {key: f"fixed_{i}" for i, key in enumerate(fixed)}
    group_columns = {key: f"group_{i}" for i, key in enumerate(groups)}
    # Materialize only skinny metadata. ACL, FTS and correlated predicates
    # are evaluated once per eligible asset, not once per facet bucket.
    eligible = (
        select(
            Asset.id,
            Asset.kind,
            Asset.doc_type,
            Asset.tags,
            Asset.project_id,
            *(clause.label(scope_columns[key]) for key, clause in scopes.items()),
            *(clause.label(fixed_columns[key]) for key, clause in fixed.items()),
            *(clause.label(group_columns[key]) for key, clause in groups.items()),
        )
        .where(*base)
        .cte("facet_eligible")
        .prefix_with("MATERIALIZED")
    )

    def where(skip: str):
        return [
            eligible.c[scope_columns[scope]],
            *(eligible.c[column] for key, column in group_columns.items() if key != skip),
        ]

    counts = (
        select(
            *(
                func.count().filter(eligible.c[column]).label(column)
                for column in scope_columns.values()
            ),
            *(
                func.count().filter(*where(key.partition(":")[0]), eligible.c[column]).label(column)
                for key, column in fixed_columns.items()
            ),
        )
        .select_from(eligible)
        .cte("facet_totals")
    )
    aggregates = [
        select(literal(f"scope:{key}").label("key"), counts.c[column].label("n"))
        for key, column in scope_columns.items()
    ] + [
        select(literal(key).label("key"), counts.c[column].label("n"))
        for key, column in fixed_columns.items()
    ]
    for kind, col in (("type", eligible.c.kind), ("doctype", eligible.c.doc_type)):
        aggregates.append(
            select((literal(f"{kind}:") + col).label("key"), func.count().label("n"))
            .where(*where(kind), col.is_not(None))
            .group_by(col)
        )
    tags = select(func.unnest(eligible.c.tags).label("tag")).where(*where("tag")).subquery()
    aggregates.append(
        select((literal("tag:") + tags.c.tag).label("key"), func.count().label("n")).group_by(
            tags.c.tag
        )
    )
    # Count an asset once per project, including assignments. Do not reveal
    # assignments to projects the caller cannot access.
    assignments = (
        select(eligible.c.id, AssetProjectShare.project_id)
        .join_from(eligible, AssetProjectShare, AssetProjectShare.asset_id == eligible.c.id)
        .where(*where("project"))
    )
    if not user.acts_as_admin:
        assignments = assignments.where(
            AssetProjectShare.project_id.in_(
                select(ProjectMember.project_id).where(
                    ProjectMember.user_id == user.id, ProjectMember.accepted_at.is_not(None)
                )
            )
        )
    projects = (
        select(eligible.c.id, eligible.c.project_id)
        .where(*where("project"), eligible.c.project_id.is_not(None))
        .union(assignments)
        .subquery()
    )
    aggregates.append(
        select(
            (literal("project:") + cast(projects.c.project_id, String)).label("key"),
            func.count().label("n"),
        ).group_by(projects.c.project_id)
    )
    rows = (await session.execute(union_all(*aggregates))).all()
    return {
        "scope_counts": {
            key.removeprefix("scope:"): n for key, n in rows if key.startswith("scope:")
        },
        "filter_counts": {key: n for key, n in rows if not key.startswith("scope:")},
    }
