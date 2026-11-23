"""Arq worker of automatic Google Sheets syncs (ADR-0032):
`arq app.jobs.sheets_worker.WorkerSettings`.

Its own queue, so a backlog of syncs (each one reads a sheet and the app's
records) never delays publications, notifications or outlines of the main
worker.
"""

from __future__ import annotations

from typing import ClassVar

from arq import cron, func

from app.config import get_settings
from app.jobs.queue import worker_redis_settings
from app.jobs.tasks.sheets import sheets_auto_sweeper, sheets_auto_sync

_settings = get_settings()


class WorkerSettings:
    redis_settings = worker_redis_settings()
    queue_name = _settings.google_sheets_queue_name
    functions: ClassVar[list] = [
        sheets_auto_sweeper,
        func(sheets_auto_sync, max_tries=1, timeout=400),
    ]
    cron_jobs: ClassVar[list] = [
        # Due links by the apps' activity and the app changes the broker
        # reported, both read from the platform database.
        cron(sheets_auto_sweeper, second=set(range(0, 60, 10)), timeout=9),
    ]
    max_jobs = _settings.google_sheets_max_jobs
    # No kept results: a sync's job id must free up as soon as its run ends.
    keep_result = 0

    @staticmethod
    async def on_startup(ctx):
        import structlog

        structlog.get_logger("arq").info("sheets_worker.started")

    @staticmethod
    async def on_shutdown(ctx):
        # A stopped sync notifies its owner, possibly by web push.
        from app.services.notifications.channels import webpush

        await webpush.close_client()
