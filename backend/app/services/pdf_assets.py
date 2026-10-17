"""PDF documents (`pdf_doc`, ADR-0013): the PDF entry of the document registry in
`services.documents`. Page texts feed `search_content` form-feed separated, so
a search hit maps back to its page; OCR text (ADR-0021) is merged by
`_ocr_overlay`.
"""

from __future__ import annotations

from typing import Any

from app.config import Settings
from app.constants import DOCUMENT_FILES
from app.pdf_extract import has_pdf_signature
from app.pdf_markdown import pages_markdown, search_text
from app.services.documents import DocumentType, OcrSupport, RecognizedPages, register


def _child_args(settings: Settings) -> list[str]:
    return [
        str(settings.pdf_extract_max_pages),
        str(settings.pdf_extract_max_chars),
        str(settings.pdf_extract_memory_bytes),
    ]


def _meta(extraction: dict[str, Any]) -> dict[str, Any]:
    pages = extraction["pages"]
    ocr_pages = set(extraction.get("ocr_pages", ()))
    hidden = set(extraction.get("hidden_text_pages", ()))
    numbered = list(enumerate(pages, start=1))
    return {
        "page_count": extraction["page_count"],
        # Pages whose text comes from the file; OCR text is counted apart.
        "text_page_count": sum(1 for n, text in numbered if text and n not in ocr_pages),
        "ocr_page_count": sum(1 for n in ocr_pages if pages[n - 1]),
        # Extracted pages without a text layer: what OCR reads on its own.
        # Pages past the extraction limit (`None`) are not counted.
        "untexted_page_count": sum(
            1 for n, text in numbered if text == "" or (n in ocr_pages and n not in hidden)
        ),
        # Scans whose text is an invisible layer saved with the file (by the
        # scanner or an OCR tool), not replaced by an OCR run yet.
        "hidden_text_page_count": len(hidden - ocr_pages),
        "bookmarks": extraction["bookmarks"],
    }


def _ocr_overlay(extraction: dict[str, Any], recognized: RecognizedPages) -> dict[str, Any]:
    """The extraction with OCR text on the pages OCR may replace: those
    without a text layer and scans with an invisible saved layer. A page
    whose text is drawn visibly keeps it, whatever a stale result says."""
    pages = list(extraction["pages"])
    hidden = set(extraction.get("hidden_text_pages", ()))
    applied = []
    for number, text in sorted(recognized.texts.items()):
        if 1 <= number <= len(pages) and (pages[number - 1] == "" or number in hidden):
            pages[number - 1] = text
            applied.append(number)
    return {
        **extraction,
        "pages": pages,
        "ocr_pages": applied,
        "ocr_markdown": recognized.markdown,
    }


def _ocr_targets(extraction: dict[str, Any], replace_hidden: bool) -> list[int]:
    wanted = {n for n, text in enumerate(extraction["pages"], start=1) if text == ""}
    if replace_hidden:
        wanted.update(extraction.get("hidden_text_pages", ()))
    return sorted(wanted)


def _pages_without_text(meta: dict[str, Any]) -> int:
    # Metas written before OCR (ADR-0021) have no `untexted_page_count`.
    if "untexted_page_count" in meta:
        return int(meta["untexted_page_count"])
    return max(0, int(meta["page_count"]) - int(meta["text_page_count"]))


register(
    DocumentType(
        kind="pdf_doc",
        stem="pdf",
        module="app.pdf_extract",
        extensions=DOCUMENT_FILES["pdf_doc"][0],
        not_editable_code="pdf_not_editable",
        wrong_file_code=DOCUMENT_FILES["pdf_doc"][1],
        too_large_code="pdf_too_large",
        failed_code="pdf_extraction_failed",
        payload_key="pdf",
        inline_html=False,
        untitled="PDF document",
        max_bytes=lambda s: s.pdf_max_bytes,
        timeout=lambda s: s.pdf_extract_timeout_seconds,
        child_args=_child_args,
        precheck=lambda data: None if has_pdf_signature(data) else "invalid_pdf",
        body=lambda extraction: pages_markdown(
            extraction["pages"],
            set(extraction.get("ocr_pages", ())),
            ocr_markdown=bool(extraction.get("ocr_markdown")),
        ),
        search_text=lambda extraction: search_text(extraction["pages"]),
        meta=_meta,
        summary=lambda meta: {
            "page_count": meta["page_count"],
            "text_page_count": meta["text_page_count"],
            "ocr_page_count": meta.get("ocr_page_count", 0),
        },
        ocr=OcrSupport(
            overlay=_ocr_overlay,
            pages_without_text=_pages_without_text,
            pages_with_hidden_text=lambda meta: int(meta.get("hidden_text_page_count", 0)),
            pages_with_ocr_text=lambda meta: int(meta.get("ocr_page_count", 0)),
            targets=_ocr_targets,
        ),
    )
)
