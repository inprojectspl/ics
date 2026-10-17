"""OCR state of a document version and the ways a run starts (ADR-0021).

not_requested (no row) -> queued -> running -> done | failed
done | failed | not_requested -> queued      (a request or a retry)
running -> queued | failed                   (sweeper: interrupted run)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

import structlog
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.domain_errors import ConflictError, InvalidInputError
from app.models import Asset, DocumentOcr
from app.services import documents
from app.util import now as utc_now

log = structlog.get_logger(__name__)

RUN_FUNCTION = "ocr_document"
ACTIVE = ("queued", "running")

OcrStatus = Literal["not_requested", "queued", "running", "done", "failed"]


class OcrProviderInfo(BaseModel):
    """An engine a reader may pick; `needs_api_key` for a cloud one."""

    name: str
    needs_api_key: bool


def provider_infos(settings: Settings) -> list[OcrProviderInfo]:
    from app.services.ocr.providers import PROVIDERS  # providers import the documents chain

    return [
        OcrProviderInfo(name=name, needs_api_key=PROVIDERS[name].needs_api_key)
        for name in settings.ocr_providers
        if name in PROVIDERS
    ]


class OcrState(BaseModel):
    """The `ocr` block of the API responses. `pages_with_hidden_text` are
    scans with an invisible text layer of unknown quality, which OCR replaces
    only on request. `available` is false when the operator turned OCR off."""

    status: OcrStatus
    pages_without_text: int
    pages_with_hidden_text: int = 0
    available: bool
    provider: str | None = None
    requested_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    pages_total: int | None = None
    pages_done: int | None = None
    pages_recognized: int | None = None
    error_code: str | None = None
    # Engines a request may name; the first is the default.
    providers: list[OcrProviderInfo] = []


def ocr_view(row: DocumentOcr, settings: Settings) -> OcrState:
    # Every field but the settings-driven ones is a column of the row.
    columns = OcrState.model_fields.keys() - {"available", "providers"}
    return OcrState(
        **{name: getattr(row, name) for name in columns},
        available=settings.ocr_enabled,
        providers=provider_infos(settings),
    )


async def ocr_state(
    session: AsyncSession,
    asset: Asset,
    version: int,
    settings: Settings,
    *,
    meta: dict[str, Any] | None = None,
) -> OcrState | None:
    """OCR block of one version, None for a kind OCR does not apply to. The
    document's meta (loaded unless passed) is read only without a run row."""
    if not documents.supports_ocr(asset.kind):
        return None
    row = await session.get(DocumentOcr, (asset.id, version), populate_existing=True)
    if row is not None:
        return ocr_view(row, settings)
    if meta is None:
        meta = await documents.load_meta(asset, version, settings)
    return OcrState(
        status="not_requested",
        pages_without_text=documents.pages_without_text(asset.kind, meta),
        pages_with_hidden_text=documents.pages_with_hidden_text(asset.kind, meta),
        available=settings.ocr_enabled,
        providers=provider_infos(settings),
    )


async def ocr_block(
    session: AsyncSession,
    asset: Asset,
    version: int,
    settings: Settings,
    *,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """`ocr_state` as the JSON of a response body."""
    state = await ocr_state(session, asset, version, settings, meta=meta)
    return state.model_dump(mode="json") if state is not None else None


async def state_tag(session: AsyncSession, asset: Asset, version: int, settings: Settings) -> str:
    """What of the OCR state an ETag must follow (a run moves on without a
    new version), from the row alone: no storage read before a 304."""
    if not documents.supports_ocr(asset.kind):
        return "-"
    row = await session.get(DocumentOcr, (asset.id, version), populate_existing=True)
    status = f"{row.status}.{row.pages_done or 0}" if row else "none"
    return f"{status}.{settings.ocr_enabled:d}"


def job_id(row: DocumentOcr) -> str:
    """Arq job id of the row's current attempt. A new request or a requeued
    attempt gets a new id; enqueueing the same attempt twice (the sweeper
    after a lost enqueue) is a no-op."""
    stamp = int(row.requested_at.timestamp() * 1000)
    return f"ocr:{row.asset_id}:{row.version}:{stamp}:{row.attempts}"


def _queue(
    row: DocumentOcr,
    requested_by: UUID | None,
    meta: dict[str, Any],
    kind: str,
    *,
    replace_hidden_text: bool,
    provider: str,
) -> None:
    row.status = "queued"
    row.provider = provider
    row.requested_by = requested_by
    row.requested_at = utc_now()
    row.started_at = row.finished_at = row.heartbeat_at = None
    row.attempts = 0
    row.pages_without_text = documents.pages_without_text(kind, meta)
    row.pages_with_hidden_text = documents.pages_with_hidden_text(kind, meta)
    # Not narrowed by the count: after a run that replaced the saved layer
    # the meta shows no hidden pages, yet a new run must read them again.
    # The run takes its pages from a fresh extraction anyway.
    row.replace_hidden_text = replace_hidden_text
    row.pages_total = row.pages_done = row.pages_recognized = None
    row.error_code = None


async def request_ocr(
    session: AsyncSession,
    asset: Asset,
    settings: Settings,
    *,
    requested_by: UUID | None,
    provider: str | None = None,
    api_key: str | None = None,
) -> DocumentOcr:
    """Queue OCR of the current version (first run or retry). A cloud
    `provider` needs `api_key`, which the caller stores with `secrets.store`
    after the commit, then calls `enqueue`."""
    if not documents.supports_ocr(asset.kind):
        raise InvalidInputError("ocr_not_supported", "OCR applies to PDF documents only")
    if not settings.ocr_enabled:
        raise ConflictError("ocr_disabled", "OCR is turned off on this server")
    allowed = {info.name: info for info in provider_infos(settings)}
    name = provider or settings.ocr_provider
    if name not in allowed:
        raise InvalidInputError("ocr_provider_unknown", f"OCR engines: {', '.join(allowed)}")
    if allowed[name].needs_api_key and not api_key:
        raise InvalidInputError("ocr_api_key_required", f"the {name} engine needs an API key")
    meta = await documents.load_meta(asset, asset.version, settings)
    # Pages with text from an earlier run count too: a saved layer an
    # earlier run replaced does not show as hidden in the meta.
    if (
        documents.pages_without_text(asset.kind, meta) == 0
        and documents.pages_with_hidden_text(asset.kind, meta) == 0
        and documents.pages_with_ocr_text(asset.kind, meta) == 0
    ):
        raise ConflictError("ocr_not_needed", "every page has a visible text layer")
    row = await session.get(DocumentOcr, (asset.id, asset.version), populate_existing=True)
    if row is None:
        row = DocumentOcr(asset_id=asset.id, version=asset.version)
        session.add(row)
    else:
        # Locked only on the way to the write the caller commits (a refusal
        # holds no lock); rechecked after locking, so of two requests at
        # once one queues the run and the other sees it active.
        if row.status not in ACTIVE:
            await session.refresh(row, with_for_update=True)
        if row.status in ACTIVE:
            raise ConflictError(
                "ocr_in_progress", "OCR of this version is already queued or running"
            )
    _queue(row, requested_by, meta, asset.kind, replace_hidden_text=True, provider=name)
    return row


def queue_after_write(
    session: AsyncSession,
    asset: Asset,
    version: int,
    converted: dict[str, Any],
    settings: Settings,
    *,
    requested_by: UUID | None,
) -> DocumentOcr | None:
    """Automatic OCR of a version written just now, when it has pages
    without a text layer. A saved invisible layer is left alone: replacing
    text the file carries is the reader's call. Added to the write's own
    transaction; the caller enqueues after the commit."""
    if not (settings.ocr_enabled and settings.ocr_auto and documents.supports_ocr(asset.kind)):
        return None
    if documents.pages_without_text(asset.kind, converted) == 0:
        return None
    row = DocumentOcr(asset_id=asset.id, version=version)
    _queue(
        row,
        requested_by,
        converted,
        asset.kind,
        replace_hidden_text=False,
        provider=settings.ocr_provider,
    )
    session.add(row)
    return row


async def enqueue(row: DocumentOcr | None, settings: Settings) -> None:
    """Hand a committed queued row to the OCR worker. Best effort: when Redis
    is down the row stays queued and the sweeper enqueues it later."""
    if row is None:
        return
    from app.jobs.queue import enqueue as enqueue_job  # readers never need the queue

    try:
        await enqueue_job(
            RUN_FUNCTION,
            str(row.asset_id),
            row.version,
            _job_id=job_id(row),
            _queue_name=settings.ocr_queue_name,
        )
    except Exception as exc:
        log.warning("ocr_enqueue_failed", asset_id=str(row.asset_id), error=str(exc))
