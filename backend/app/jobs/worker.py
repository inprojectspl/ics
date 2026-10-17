"""Arq worker entrypoint: `arq app.jobs.worker.WorkerSettings`. OCR runs are in
`ocr_worker`."""

from __future__ import annotations

from typing import ClassVar

from arq import cron

from app.config import get_settings
from app.jobs.queue import worker_redis_settings
from app.jobs.tasks.cleanup import cleanup_oauth_artifacts, cleanup_old_email_outbox
from app.jobs.tasks.notify import notifications_sweeper, notify_asset_event
from app.jobs.tasks.ocr import ocr_sweeper
from app.jobs.tasks.outline import outline_stale_sweeper, rebuild_outline


class WorkerSettings:
    # `ClassVar` for RUF012: Arq reads these as class-level constants.
    redis_settings = worker_redis_settings()
    functions: ClassVar[list] = [
        rebuild_outline,
        outline_stale_sweeper,
        cleanup_oauth_artifacts,
        cleanup_old_email_outbox,
        ocr_sweeper,
        notify_asset_event,
        notifications_sweeper,
    ]
    cron_jobs: ClassVar[list] = [
        cron(outline_stale_sweeper, minute=set(range(0, 60))),  # every minute
        cron(cleanup_oauth_artifacts, minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}),
        # Retention: once a day at 03:00, when load is low.
        cron(cleanup_old_email_outbox, hour={3}, minute={0}),
        cron(ocr_sweeper, minute=set(range(0, 60))),
        # Debounced version events and e-mail / Chat batches (ADR-0023).
        cron(notifications_sweeper, second=set(range(0, 60, 5)), timeout=60),
    ]
    max_jobs = get_settings().arq_max_jobs
    job_timeout = get_settings().arq_job_timeout
    max_tries = 3
    keep_result = 60  # seconds, for status polling

    @staticmethod
    async def on_startup(ctx):
        import structlog

        structlog.get_logger("arq").info("worker.started")

    @staticmethod
    async def on_shutdown(ctx):
        import structlog

        from app.services.notifications.channels import webpush

        await webpush.close_client()

        structlog.get_logger("arq").info("worker.shutdown")
