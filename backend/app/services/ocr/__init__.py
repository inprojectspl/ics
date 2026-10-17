"""OCR of scanned document pages (ADR-0021): state and requests (`state`),
run execution and the sweeper (`runs`), engines (`providers`)."""

from app.services.ocr.state import (
    OcrState,
    enqueue,
    ocr_block,
    ocr_state,
    ocr_view,
    queue_after_write,
    request_ocr,
    state_tag,
)

__all__ = [
    "OcrState",
    "enqueue",
    "ocr_block",
    "ocr_state",
    "ocr_view",
    "queue_after_write",
    "request_ocr",
    "state_tag",
]
