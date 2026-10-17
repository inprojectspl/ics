"""Word and OpenDocument text documents (`office_doc`, ADR-0014): the Office
entry of the document registry in `services.documents`. `app.office_extract`
detects the format from the content (`.docx`, `.odt`, `.doc`).
"""

from __future__ import annotations

from app.config import Settings
from app.constants import DOCUMENT_FILES
from app.office_extract import OLE_MAGIC, ZIP_MAGIC
from app.services.documents import DocumentType, register


def _child_args(settings: Settings) -> list[str]:
    return [
        str(settings.office_convert_max_chars),
        str(settings.office_max_unzipped_bytes),
        str(settings.office_convert_memory_bytes),
    ]


register(
    DocumentType(
        kind="office_doc",
        stem="doc",
        module="app.office_extract",
        extensions=DOCUMENT_FILES["office_doc"][0],
        not_editable_code="office_not_editable",
        wrong_file_code=DOCUMENT_FILES["office_doc"][1],
        too_large_code="office_too_large",
        failed_code="office_conversion_failed",
        payload_key="document",
        inline_html=True,
        untitled="Document",
        max_bytes=lambda s: s.office_max_bytes,
        timeout=lambda s: s.office_convert_timeout_seconds,
        child_args=_child_args,
        precheck=lambda data: (
            None if data.startswith((OLE_MAGIC, ZIP_MAGIC)) else "invalid_office_document"
        ),
        body=lambda extraction: extraction["markdown"],
        search_text=lambda extraction: extraction["markdown"] or None,
        meta=lambda extraction: {
            "format": extraction["format"],
            "images": extraction["images"],
        },
        summary=lambda meta: {"source_format": meta["format"], "images": meta["images"]},
    )
)
