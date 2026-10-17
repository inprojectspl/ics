"""Arq tasks of document OCR (ADR-0021). The run itself is in
`services.ocr.runs`; these wrappers only bind the worker's session factory.

`ocr_document` runs in the OCR worker (`app.jobs.ocr_worker`, own queue);
`ocr_sweeper` is a cron of the main worker, so it keeps running while the
OCR worker is busy with a long document."""

from __future__ import annotations

from uuid import UUID

from app.config import get_settings
from app.db import SessionLocal
from app.services.ocr import runs


async def ocr_document(ctx: dict, asset_id_str: str, version: int) -> dict:
    return await runs.run(SessionLocal, UUID(asset_id_str), version, get_settings())


async def ocr_sweeper(ctx: dict) -> dict:
    return await runs.sweep(SessionLocal, get_settings())
