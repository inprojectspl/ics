"""Arq worker of document OCR (ADR-0021): `arq app.jobs.ocr_worker.OcrWorkerSettings`.

Its own queue, because OCR takes minutes of CPU per document. No Arq retries:
the main worker's sweeper requeues interrupted runs and counts attempts.
"""

from __future__ import annotations

from typing import ClassVar

from arq import func

from app.config import get_settings
from app.jobs.queue import worker_redis_settings
from app.jobs.tasks.ocr import ocr_document

_settings = get_settings()


class OcrWorkerSettings:
    redis_settings = worker_redis_settings()
    queue_name = _settings.ocr_queue_name
    # The run enforces `ocr_timeout_seconds` itself and records the failure;
    # Arq's limit is only a backstop past that.
    functions: ClassVar[list] = [
        func(ocr_document, timeout=_settings.ocr_timeout_seconds + 300, max_tries=1)
    ]
    max_jobs = _settings.ocr_concurrency
    # No stored results: a retry of the same row enqueues under a new job id
    # anyway, and nothing polls Arq for the outcome (the row holds it).
    keep_result = 0

    @staticmethod
    async def on_startup(ctx):
        import structlog

        structlog.get_logger("arq").info("ocr_worker.started")
