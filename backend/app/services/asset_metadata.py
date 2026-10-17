"""Document metadata writes (ADR-0015): summary, doc type, maintainer, review
date, language and type-specific `properties`. Nothing here commits; the
caller records the audit entry and commits.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

import orjson
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, json_schema
from app.domain_errors import InvalidInputError
from app.models import Asset, DocType, User
from app.services.asset_projection import detail_fields, load_metadata, metadata_fields
from app.util import now as utc_now

SummarySource = Literal["human", "agent"]

MAX_SUMMARY_CHARS = 1000
MAX_PROPERTIES_BYTES = 16 * 1024
_LANGUAGE_RE = re.compile(r"[a-z]{2,3}(-[A-Za-z0-9]{2,4})?")


def source_for_transport(transport: str | None) -> SummarySource:
    """A write through an MCP bearer token is the agent's; anything else
    (cookie session, dev stub) is a human edit."""
    return "agent" if audit.is_agent_transport(transport) else "human"


def _invalid(field: str, detail: str) -> InvalidInputError:
    return InvalidInputError("metadata_invalid", f"{field}: {detail}", field=field)


def normalize_summary(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if len(value) > MAX_SUMMARY_CHARS:
        raise _invalid("summary", f"at most {MAX_SUMMARY_CHARS} characters")
    return value or None


async def usable_doc_type(session: AsyncSession, key: str) -> DocType:
    """A doc type an asset may be given now: it exists and is not archived."""
    doc_type = await session.get(DocType, key)
    if doc_type is None or doc_type.archived_at is not None:
        raise InvalidInputError("doc_type_unknown", f"unknown document type: {key}")
    return doc_type


def set_summary(asset: Asset, summary: str | None, source: SummarySource) -> None:
    asset.summary = summary
    asset.summary_source = source if summary else None
    asset.summary_version = asset.version if summary else None


def default_review_due(doc_type: DocType | None, now: datetime) -> datetime | None:
    if doc_type is None or doc_type.default_review_days is None:
        return None
    return now + timedelta(days=doc_type.default_review_days)


def _check_properties(properties: Any, doc_type: DocType | None) -> dict[str, Any]:
    if not isinstance(properties, dict):
        raise _invalid("properties", "must be an object")
    if len(orjson.dumps(properties)) > MAX_PROPERTIES_BYTES:
        raise _invalid("properties", f"at most {MAX_PROPERTIES_BYTES} bytes")
    schema = doc_type.properties_schema if doc_type else None
    if schema:
        path = json_schema.first_error(schema, properties, "properties")
        if path is not None:
            raise _invalid(path, "does not match the document type schema")
    return properties


async def update_metadata(
    session: AsyncSession,
    asset: Asset,
    changes: Mapping[str, Any],
    *,
    source: SummarySource,
) -> list[str]:
    """Apply the fields present in `changes`; return the names of the fields
    whose value actually changed (for the audit entry)."""
    await session.refresh(asset, ["summary"])
    now = utc_now()
    changed: list[str] = []

    if "summary" in changes:
        summary = normalize_summary(changes["summary"])
        if summary != asset.summary:
            set_summary(asset, summary, source)
            changed.append("summary")

    doc_type: DocType | None = None
    type_changed = "doc_type" in changes and changes["doc_type"] != asset.doc_type
    if type_changed and changes["doc_type"] is not None:
        doc_type = await usable_doc_type(session, changes["doc_type"])
    elif not type_changed and asset.doc_type is not None:
        # The current type may be archived since; it stays on the asset.
        doc_type = await session.get(DocType, asset.doc_type)
    if type_changed:
        asset.doc_type = changes["doc_type"]
        changed.append("doc_type")

    if "maintainer_id" in changes and changes["maintainer_id"] != asset.maintainer_id:
        maintainer_id = changes["maintainer_id"]
        if maintainer_id is not None and await session.get(User, maintainer_id) is None:
            raise _invalid("maintainer_id", "user does not exist")
        asset.maintainer_id = maintainer_id
        changed.append("maintainer_id")

    if "review_due_at" in changes:
        due = changes["review_due_at"]
        if due is not None and due.tzinfo is None:
            due = due.replace(tzinfo=UTC)
        if due != asset.review_due_at:
            asset.review_due_at = due
            changed.append("review_due_at")
    elif type_changed and asset.review_due_at is None:
        due = default_review_due(doc_type, now)
        if due is not None:
            asset.review_due_at = due
            changed.append("review_due_at")

    if "language" in changes and changes["language"] != asset.language:
        language = changes["language"]
        if language is not None and not _LANGUAGE_RE.fullmatch(language):
            raise _invalid("language", "expected a language tag such as 'pl' or 'en-GB'")
        asset.language = language
        changed.append("language")

    if "properties" in changes or type_changed:
        new = changes.get("properties", asset.properties)
        properties = _check_properties({} if new is None else new, doc_type)
        if properties != asset.properties:
            asset.properties = properties
            changed.append("properties")

    return changed


@dataclass(frozen=True)
class CreateMetadata:
    """Metadata given with a new asset, validated before any storage write
    so an unknown doc type leaves nothing behind."""

    doc_type: DocType | None = None
    summary: str | None = None
    source: SummarySource = "human"

    def apply(self, asset: Asset) -> None:
        if self.doc_type is not None:
            asset.doc_type = self.doc_type.key
            asset.review_due_at = default_review_due(self.doc_type, utc_now())
        if self.summary:
            asset.summary = self.summary
            asset.summary_source = self.source
            # A new asset is v1; the column default is not applied before flush.
            asset.summary_version = 1


async def prepare_create_metadata(
    session: AsyncSession,
    *,
    doc_type: str | None,
    summary: str | None,
    source: SummarySource,
) -> CreateMetadata:
    return CreateMetadata(
        doc_type=await usable_doc_type(session, doc_type) if doc_type else None,
        summary=normalize_summary(summary),
        source=source,
    )


async def mark_reviewed(session: AsyncSession, asset: Asset, reviewer_id: UUID) -> None:
    """ "Still current": a review without a content change. The next review is
    due after the doc type's period (archived types included, they stay on
    their assets); without a period the due date is cleared."""
    now = utc_now()
    doc_type = await session.get(DocType, asset.doc_type) if asset.doc_type else None
    asset.reviewed_at = now
    asset.reviewed_by = reviewer_id
    asset.review_due_at = default_review_due(doc_type, now)


async def metadata_detail(session: AsyncSession, asset: Asset, viewer: User) -> dict[str, Any]:
    """The full metadata of one asset as `viewer` sees it, returned by the
    metadata writes."""
    row = (await load_metadata(session, [asset], viewer)).get(asset.id)
    return {
        "id": str(asset.id),
        "version": asset.version,
        **metadata_fields(asset, row, utc_now(), preview=False),
        **detail_fields(asset),
    }
