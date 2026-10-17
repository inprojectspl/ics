"""Mistral OCR (`mistral` provider, ADR-0021): pages go to `/v1/ocr` with the
reader's API key and come back as Markdown. The PDF is cut into chunks of
`ICS_OCR_MISTRAL_CHUNK_PAGES` so one failed request costs one chunk. Mistral
keeps request data for 30 days unless the account has zero data retention.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Sequence
from typing import Any

import httpx

from app.child_process import run_child
from app.config import Settings
from app.services.ocr.base import OcrFailure, PageCallback

# Attempts per chunk on a rate limit or a server error, and the longest wait.
_ATTEMPTS = 3
_MAX_BACKOFF = 30.0

# HTTP status of a refused request -> run error code.
_REFUSALS = {
    401: "ocr_api_key_invalid",
    403: "ocr_api_key_invalid",
    402: "ocr_provider_quota",
    413: "ocr_provider_too_large",
}


class MistralProvider:
    name = "mistral"
    needs_api_key = True
    markdown = True
    # Tests replace the network with an `httpx.MockTransport`.
    transport: httpx.AsyncBaseTransport | None = None

    async def recognize(
        self,
        pdf: bytes,
        pages: Sequence[int],
        settings: Settings,
        on_page: PageCallback,
        *,
        api_key: str | None = None,
    ) -> str:
        if not api_key:
            raise OcrFailure("ocr_api_key_missing")
        engine = f"mistral {settings.ocr_mistral_model}"
        size = max(1, settings.ocr_mistral_chunk_pages)
        timeout = httpx.Timeout(settings.ocr_page_timeout_seconds * 2, connect=15)
        async with httpx.AsyncClient(timeout=timeout, transport=self.transport) as client:
            for start in range(0, len(pages), size):
                chunk = list(pages[start : start + size])
                part = await _split(pdf, chunk, settings)
                body = await self._request(client, part, len(chunk), api_key, settings)
                if model := body.get("model"):
                    engine = f"mistral {model}"
                texts = {
                    int(p["index"]): str(p.get("markdown") or "")
                    for p in body.get("pages") or []
                    if isinstance(p, dict) and "index" in p
                }
                for offset, number in enumerate(chunk):
                    await on_page(number, texts.get(offset, ""))
        return engine

    async def _request(
        self,
        client: httpx.AsyncClient,
        part: bytes,
        count: int,
        api_key: str,
        settings: Settings,
    ) -> dict[str, Any]:
        payload = {
            "model": settings.ocr_mistral_model,
            "document": {
                "type": "document_url",
                "document_url": "data:application/pdf;base64," + base64.b64encode(part).decode(),
            },
            "pages": list(range(count)),
            "include_image_base64": False,
        }
        headers = {"Authorization": f"Bearer {api_key}"}
        for attempt in range(_ATTEMPTS):
            try:
                r = await client.post(settings.ocr_mistral_url, json=payload, headers=headers)
            except httpx.TimeoutException:
                raise OcrFailure("ocr_page_timeout") from None
            except httpx.HTTPError:
                if attempt + 1 == _ATTEMPTS:
                    raise OcrFailure("ocr_provider_unreachable") from None
                await asyncio.sleep(2**attempt)
                continue
            if r.status_code == 200:
                body: dict[str, Any] = r.json()
                return body
            if r.status_code in _REFUSALS:
                raise OcrFailure(_REFUSALS[r.status_code])
            if r.status_code == 429 or r.status_code >= 500:
                if attempt + 1 == _ATTEMPTS:
                    raise OcrFailure(
                        "ocr_provider_rate_limited"
                        if r.status_code == 429
                        else "ocr_provider_error"
                    )
                await asyncio.sleep(_retry_after(r, attempt))
                continue
            raise OcrFailure("ocr_provider_rejected")
        raise OcrFailure("ocr_provider_error")  # pragma: no cover - the loop always returns


def _retry_after(response: httpx.Response, attempt: int) -> float:
    try:
        wait = float(response.headers.get("retry-after", ""))
    except ValueError:
        wait = 2.0**attempt
    return min(max(wait, 0.0), _MAX_BACKOFF)


async def _split(pdf: bytes, pages: Sequence[int], settings: Settings) -> bytes:
    args = [
        "--pages",
        ",".join(str(p) for p in pages),
        "--memory",
        str(settings.pdf_extract_memory_bytes),
    ]
    try:
        out = await run_child("app.pdf_split", args, pdf, settings.pdf_extract_timeout_seconds)
    except TimeoutError:
        raise OcrFailure("ocr_page_timeout") from None
    if out is None:
        raise OcrFailure("ocr_invalid_pdf")
    return out
