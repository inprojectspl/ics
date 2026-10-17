"""Registry of the OCR engines (ADR-0021): a cloud engine is one more
class in `PROVIDERS` (and in `ICS_OCR_PROVIDERS`)."""

from __future__ import annotations

from app.services.ocr.base import OcrFailure, OcrProvider, PageCallback
from app.services.ocr.local import LocalProvider
from app.services.ocr.mistral import MistralProvider

__all__ = [
    "PROVIDERS",
    "LocalProvider",
    "MistralProvider",
    "OcrFailure",
    "OcrProvider",
    "PageCallback",
    "get_provider",
]

PROVIDERS: dict[str, OcrProvider] = {
    LocalProvider.name: LocalProvider(),
    MistralProvider.name: MistralProvider(),
}


def get_provider(name: str) -> OcrProvider:
    """The provider registered as `name`; `OcrFailure` for an unknown one,
    so a misconfigured engine fails the run with a code instead of crashing
    the worker."""
    provider = PROVIDERS.get(name)
    if provider is None:
        raise OcrFailure("ocr_provider_unavailable")
    return provider
