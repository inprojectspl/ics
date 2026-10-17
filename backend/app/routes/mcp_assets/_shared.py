"""Shared constants, helpers, and cursor encoding for MCP endpoints."""

from __future__ import annotations

import base64
import re
from datetime import UTC, datetime
from uuid import UUID

import orjson
from sqlalchemy import ColumnElement, and_, case, literal

from app.collections_io import MAX_LINES_RANGE
from app.constants import DOCUMENT_FILES
from app.models import Asset, AssetShare, ProjectMember, User
from app.permissions import project_share_member_exists
from app.services import graph_signals
from app.services.freshness import FilterableFreshness, freshness_filter


def metadata_filters(
    *,
    doc_type: list[str] | None,
    freshness: list[FilterableFreshness] | None,
    tag: list[str] | None,
    maintainer: UUID | None,
    now: datetime,
    viewer: User,
) -> list[ColumnElement[bool]]:
    """Metadata filters shared by `/index` and `/search-mcp` (ADR-0015).
    Values within one filter are OR-ed, except tags, which must all be present.
    Freshness is as `viewer` sees it: only a visible successor supersedes."""
    clauses: list[ColumnElement[bool]] = []
    if doc_type:
        clauses.append(Asset.doc_type.in_(doc_type))
    if freshness:
        superseded = graph_signals.visible_successor_exists(viewer, Asset.id)
        clauses.append(freshness_filter(freshness, now, superseded=superseded))
    if tag:
        # `tags @> ARRAY[...]`: served by the GIN index on tags.
        clauses.append(Asset.tags.contains(tag))
    if maintainer is not None:
        clauses.append(Asset.maintainer_id == maintainer)
    return clauses


_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,30}[a-z0-9]$")
_MAX_TAGS = 20
_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500
# Defined in collections_io (shared with share resolve); aliased for this package.
_MAX_LINES_RANGE = MAX_LINES_RANGE
_HTML_BUNDLE_MAX_FILES = 50
# file-mcp: cap on base64 of bundle binaries. Above it an agent can't do
# anything useful with the payload anyway, and the response grows ~1.33x.
_MCP_BASE64_MAX_BYTES = 1 * 1024 * 1024
# Kinds read per file by the -mcp endpoints (file-mcp, files-mcp).
_MCP_FILE_KINDS = frozenset({"md_single", "md_collection", "html_bundle", *DOCUMENT_FILES})


def _encode_cursor(updated_at: datetime, id_: UUID) -> str:
    payload = {"u": updated_at.timestamp(), "i": str(id_)}
    return base64.urlsafe_b64encode(orjson.dumps(payload)).decode()


def _decode_cursor(value: str) -> tuple[datetime, UUID] | None:
    try:
        payload = orjson.loads(base64.urlsafe_b64decode(value.encode() + b"=="))
        return datetime.fromtimestamp(payload["u"], tz=UTC), UUID(payload["i"])
    except Exception:
        return None


def _build_role_case(user: User):
    """SQL CASE equivalent of `permissions.effective_role()` (admin bypass
    included) over pre-joined ProjectMember and AssetShare rows."""
    if user.acts_as_admin:
        return literal("owner_file")
    user_id = user.id
    return case(
        (Asset.owner_id == user_id, "owner_file"),
        (
            and_(
                ProjectMember.user_id == user_id,
                ProjectMember.accepted_at.is_not(None),
                ProjectMember.role == "owner",
            ),
            "project_owner",
        ),
        (
            and_(
                ProjectMember.user_id == user_id,
                ProjectMember.accepted_at.is_not(None),
                ProjectMember.role == "editor",
            ),
            "editor",
        ),
        (AssetShare.role == "editor", "editor"),
        (project_share_member_exists(user_id, editor=True), "editor"),
        (
            and_(
                ProjectMember.user_id == user_id,
                ProjectMember.accepted_at.is_not(None),
                ProjectMember.role == "viewer",
            ),
            "viewer",
        ),
        (AssetShare.role == "viewer", "viewer"),
        (project_share_member_exists(user_id), "viewer"),
        else_=None,
    )
