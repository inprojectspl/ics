"""Execution of an OCR run and the sweeper that keeps runs moving (ADR-0021).
`run` claims the queued row, so a duplicate job does nothing, and ends in
`done` or `failed`; only a killed worker leaves `running`, which `sweep` fixes.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

import orjson
import structlog
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.collections_io import read_bytes_at_version
from app.config import Settings
from app.domain_errors import DomainError
from app.jobs.queue import enqueue as enqueue_job
from app.models import Asset, DocumentOcr, User
from app.services import asset_security, documents, read_size, relation_extraction
from app.services.documents import RecognizedPages
from app.services.ocr import secrets
from app.services.ocr.providers import OcrFailure, OcrProvider, get_provider
from app.services.ocr.state import enqueue
from app.services.upload import one_chunk
from app.services.versions import entry_path_at_version
from app.storage import storage_from_url
from app.util import now as utc_now

log = structlog.get_logger(__name__)

# Progress is written at most this often (seconds); the heartbeat with it.
_PROGRESS_EVERY = 2.0


async def _claim(sessions: async_sessionmaker[AsyncSession], asset_id: UUID, version: int) -> bool:
    now = utc_now()
    async with sessions() as session:
        claimed = await session.execute(
            update(DocumentOcr)
            .where(
                DocumentOcr.asset_id == asset_id,
                DocumentOcr.version == version,
                DocumentOcr.status == "queued",
            )
            .values(
                status="running",
                started_at=now,
                heartbeat_at=now,
                attempts=DocumentOcr.attempts + 1,
                pages_done=0,
            )
            .returning(DocumentOcr.asset_id)
        )
        await session.commit()
        return claimed.first() is not None


async def _update(
    sessions: async_sessionmaker[AsyncSession], asset_id: UUID, version: int, **values: Any
) -> None:
    async with sessions() as session:
        await session.execute(
            update(DocumentOcr)
            .where(
                DocumentOcr.asset_id == asset_id,
                DocumentOcr.version == version,
                DocumentOcr.status == "running",
            )
            .values(heartbeat_at=utc_now(), **values)
        )
        await session.commit()


async def _fail(
    sessions: async_sessionmaker[AsyncSession], asset_id: UUID, version: int, code: str
) -> dict[str, Any]:
    log.warning("ocr_failed", asset_id=str(asset_id), version=version, code=code)
    await _update(
        sessions, asset_id, version, status="failed", error_code=code, finished_at=utc_now()
    )
    return {"asset_id": str(asset_id), "version": version, "error": code}


async def run(
    sessions: async_sessionmaker[AsyncSession], asset_id: UUID, version: int, settings: Settings
) -> dict[str, Any]:
    if not await _claim(sessions, asset_id, version):
        return {"asset_id": str(asset_id), "version": version, "skipped": "not_queued"}
    async with sessions() as session:
        asset = await session.get(Asset, asset_id)
        row = await session.get(DocumentOcr, (asset_id, version))
    if asset is None or row is None or asset.deleted_at is not None:
        await secrets.delete(asset_id, version)
        return await _fail(sessions, asset_id, version, "ocr_source_missing")
    try:
        provider = get_provider(row.provider)
        api_key = None
        if provider.needs_api_key:
            api_key = await secrets.load(asset_id, version, settings)
            if api_key is None:
                # Expired (a long queue) or never stored: the reader asks again.
                raise OcrFailure("ocr_api_key_missing")
        async with asyncio.timeout(settings.ocr_timeout_seconds):
            source = await _Source.load(asset, version, settings)
            recognized, engine = await _recognize(
                sessions,
                source,
                provider,
                settings,
                api_key=api_key,
                replace_hidden=row.replace_hidden_text,
            )
            await _store(sessions, source, recognized, engine, provider, settings)
    except TimeoutError:
        return await _fail(sessions, asset_id, version, "ocr_timeout")
    except (OcrFailure, DomainError) as exc:
        # A domain error: the extraction refused the document itself.
        return await _fail(sessions, asset_id, version, exc.code)
    except FileNotFoundError:
        return await _fail(sessions, asset_id, version, "ocr_source_missing")
    except Exception:
        log.exception("ocr_crashed", asset_id=str(asset_id), version=version)
        return await _fail(sessions, asset_id, version, "ocr_engine_failed")
    finally:
        # A retry by the sweeper finds no key and fails; a request brings a new one.
        await secrets.delete(asset_id, version)
    found = sum(1 for text in recognized.values() if text)
    await _update(
        sessions,
        asset_id,
        version,
        status="done",
        finished_at=utc_now(),
        pages_done=len(recognized),
        pages_recognized=found,
        error_code=None,
    )
    log.info("ocr_done", asset_id=str(asset_id), version=version, pages=len(recognized))
    return {"asset_id": str(asset_id), "version": version, "pages": len(recognized), "found": found}


@dataclass(frozen=True)
class _Source:
    """The version's document, read and extracted once for the whole run."""

    asset: Asset
    version: int
    entry: str
    data: bytes
    extraction: dict[str, Any]

    @classmethod
    async def load(cls, asset: Asset, version: int, settings: Settings) -> _Source:
        entry = await entry_path_at_version(asset, version, settings)
        if entry is None:
            raise FileNotFoundError(f"v{version} has no document")
        data = await read_bytes_at_version(asset, version, entry, settings)
        # A fresh extraction, not the derived meta: the page texts hold for
        # derived files written before OCR existed too.
        extraction = await documents.run_extraction(asset.kind, data, settings)
        return cls(asset, version, entry, data, extraction)


async def _recognize(
    sessions: async_sessionmaker[AsyncSession],
    source: _Source,
    provider: OcrProvider,
    settings: Settings,
    *,
    api_key: str | None,
    replace_hidden: bool,
) -> tuple[dict[int, str], str]:
    asset_id, version = source.asset.id, source.version
    ocr = documents.document_type(source.asset.kind).ocr
    targets = ocr.targets(source.extraction, replace_hidden) if ocr else []
    targets = targets[: settings.ocr_max_pages]
    await _update(sessions, asset_id, version, pages_total=len(targets))

    recognized: dict[int, str] = {}
    last_write = 0.0
    loop = asyncio.get_running_loop()

    async def on_page(number: int, text: str) -> None:
        nonlocal last_write
        recognized[number] = text
        if loop.time() - last_write >= _PROGRESS_EVERY:
            last_write = loop.time()
            await _update(sessions, asset_id, version, pages_done=len(recognized))

    if not targets:
        return recognized, "none"
    engine = await provider.recognize(source.data, targets, settings, on_page, api_key=api_key)
    return recognized, engine


async def _store(
    sessions: async_sessionmaker[AsyncSession],
    source: _Source,
    recognized: dict[int, str],
    engine: str,
    provider: OcrProvider,
    settings: Settings,
) -> None:
    """Keep the result and rebuild what depends on the text."""
    asset, version = source.asset, source.version
    storage = storage_from_url(settings.storage_url)
    result = {
        "provider": provider.name,
        "engine": engine,
        "finished_at": utc_now().isoformat(),
        "format": "markdown" if provider.markdown else "text",
        "pages": {str(n): text for n, text in sorted(recognized.items())},
    }
    await storage.put(
        documents.ocr_result_key(asset.storage_prefix, version), one_chunk(orjson.dumps(result))
    )
    converted = await documents.ingest(
        storage,
        kind=asset.kind,
        storage_prefix=asset.storage_prefix,
        version=version,
        entry_path=source.entry,
        settings=settings,
        extraction=source.extraction,
        recognized=RecognizedPages(recognized, markdown=provider.markdown),
    )
    async with sessions() as session:
        current = await session.get(Asset, asset.id, with_for_update=True)
        if current is None or current.version != version:
            # A newer version is current: its own text is already in place.
            return
        row = await session.get(DocumentOcr, (asset.id, version))
        author = await session.get(User, row.requested_by) if row and row.requested_by else None
        current.search_content = documents.search_content_of(current.kind, converted)
        await read_size.refresh_read_tokens(current, settings, converted=converted)
        await asset_security.scan_and_apply(current, settings, session, actor=author)
        await relation_extraction.extract_from_content(
            session, current, settings, author.id if author else None, converted=converted
        )
        # Page outline sizes come from the Markdown, which just changed.
        current.outline_status = "stale"
        await session.commit()
    try:
        await enqueue_job("rebuild_outline", str(asset.id), _job_id=f"outline:{asset.id}")
    except Exception as exc:
        # The outline sweeper rebuilds every stale row anyway.
        log.warning("ocr_outline_enqueue_failed", asset_id=str(asset.id), error=str(exc))


def stale_after(settings: Settings) -> timedelta:
    """Silence after which a running run counts as interrupted: longer than
    any single step that does not report progress."""
    longest = max(settings.ocr_page_timeout_seconds, settings.pdf_extract_timeout_seconds)
    return timedelta(seconds=2 * longest + 60)


# A queued row whose job never reached Redis waits this long for the sweeper.
_LOST_AFTER = timedelta(minutes=2)


async def sweep(sessions: async_sessionmaker[AsyncSession], settings: Settings) -> dict[str, Any]:
    """Requeue runs of a killed worker (or fail them after
    `ocr_max_attempts`) and enqueue queued rows whose job was lost."""
    now = utc_now()
    to_enqueue: list[DocumentOcr] = []
    failed = 0
    async with sessions() as session:
        rows = (
            await session.scalars(
                select(DocumentOcr)
                .where(
                    or_(
                        (DocumentOcr.status == "running")
                        & (DocumentOcr.heartbeat_at < now - stale_after(settings)),
                        (DocumentOcr.status == "queued")
                        & (DocumentOcr.requested_at < now - _LOST_AFTER),
                    )
                )
                .with_for_update(skip_locked=True)
            )
        ).all()
        for row in rows:
            if row.status == "running":
                if row.attempts >= settings.ocr_max_attempts:
                    row.status, row.error_code, row.finished_at = "failed", "ocr_interrupted", now
                    failed += 1
                    continue
                row.status = "queued"
            to_enqueue.append(row)
        await session.commit()
    for row in to_enqueue:
        await enqueue(row, settings)
    return {"requeued": len(to_enqueue), "failed": failed}
