"""The built-in local OCR engine (`local` provider, ADR-0021)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import orjson

from app.child_process import child
from app.config import Settings
from app.services.ocr.base import OcrFailure, PageCallback

# Label of the local engine until the child reports its version.
_ENGINE = "rapidocr"
# One page of JSON can exceed the default 64 KB line limit.
_LINE_LIMIT = 16 * 1024 * 1024


def thread_env(threads: int) -> dict[str, str]:
    """Environment of the OCR child. A thread and a malloc arena per CPU would
    make the address space outgrow the child's memory limit on a many-core
    host (`ocr_out_of_memory`), so both are capped."""
    n = str(max(1, threads))
    return {
        "OMP_NUM_THREADS": n,
        "OPENBLAS_NUM_THREADS": n,
        "MKL_NUM_THREADS": n,
        "NUMEXPR_NUM_THREADS": n,
        "MALLOC_ARENA_MAX": "2",
    }


class LocalProvider:
    """PP-OCR through RapidOCR in a child process (`app.ocr_local`), on the
    worker's CPU; no document leaves the server.

    Pages go to a fresh child in chunks of `chunk_pages`: the engine's
    memory stays bounded however long the document is, and a crash costs one
    chunk's work, not the run's."""

    name = "local"
    needs_api_key = False
    markdown = False
    module = "app.ocr_local"
    chunk_pages = 100

    async def recognize(
        self,
        pdf: bytes,
        pages: Sequence[int],
        settings: Settings,
        on_page: PageCallback,
        *,
        api_key: str | None = None,
    ) -> str:
        engine = _ENGINE
        for start in range(0, len(pages), self.chunk_pages):
            engine = await self._run_chunk(
                pdf, pages[start : start + self.chunk_pages], settings, on_page
            )
        return engine

    async def _run_chunk(
        self, pdf: bytes, pages: Sequence[int], settings: Settings, on_page: PageCallback
    ) -> str:
        args = [
            "--pages",
            ",".join(str(p) for p in pages),
            "--dpi",
            str(settings.ocr_dpi),
            "--max-pixels",
            str(settings.ocr_max_page_pixels),
            "--threads",
            str(settings.ocr_threads),
            "--memory",
            str(settings.ocr_memory_bytes),
        ]
        env = thread_env(settings.ocr_threads)
        async with child(self.module, args, line_limit=_LINE_LIMIT, env=env) as proc:
            return await self._talk(proc, pdf, pages, settings, on_page)

    async def _talk(
        self,
        proc: asyncio.subprocess.Process,
        pdf: bytes,
        pages: Sequence[int],
        settings: Settings,
        on_page: PageCallback,
    ) -> str:
        assert proc.stdin is not None and proc.stdout is not None
        # The child reads all of stdin before it prints anything.
        proc.stdin.write(pdf)
        await proc.stdin.drain()
        proc.stdin.close()
        engine = _ENGINE
        expected = iter(pages)
        # Loading the models counts as a page: both are bounded by the same wait.
        while True:
            try:
                line = await asyncio.wait_for(
                    proc.stdout.readline(), timeout=settings.ocr_page_timeout_seconds
                )
            except TimeoutError:
                raise OcrFailure("ocr_page_timeout") from None
            if not line:
                raise OcrFailure("ocr_engine_failed")
            try:
                message = orjson.loads(line)
            except orjson.JSONDecodeError:
                raise OcrFailure("ocr_engine_failed") from None
            if "error" in message:
                raise OcrFailure(str(message["error"]))
            if "engine" in message:
                engine = str(message["engine"])
            elif "page" in message:
                if message["page"] != next(expected, None):
                    raise OcrFailure("ocr_engine_failed")
                await on_page(int(message["page"]), str(message.get("text") or ""))
            elif message.get("done"):
                if next(expected, None) is not None:
                    raise OcrFailure("ocr_engine_failed")
                return engine
