"""Common types of the OCR engines (ADR-0021). A provider reports each page
through `on_page` and raises `OcrFailure` with a stable code; the whole-run
time budget is the caller's, a provider only bounds the wait for the next page
and cleans up after itself on cancellation.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol

from app.config import Settings

PageCallback = Callable[[int, str], Awaitable[None]]


class OcrFailure(Exception):
    """The engine could not read the document; `code` goes to the run row."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class OcrProvider(Protocol):
    name: str
    # The reader passes an API key with the request (a cloud engine).
    needs_api_key: bool
    # Page texts are Markdown (tables, lists) rather than plain lines.
    markdown: bool

    async def recognize(
        self,
        pdf: bytes,
        pages: Sequence[int],
        settings: Settings,
        on_page: PageCallback,
        *,
        api_key: str | None = None,
    ) -> str:
        """Read `pages` (1-based) of `pdf`, calling `on_page` once per page in
        order; return the engine label stored with the result."""
        ...
