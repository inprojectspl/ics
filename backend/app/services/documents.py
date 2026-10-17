"""Documents converted to Markdown at write time: PDF (`pdf_doc`, ADR-0013)
and Word/OpenDocument text (`office_doc`, ADR-0014).

`ingest` stores the result under `{storage_prefix}/derived/v{n}/`, outside the
`v{n}/` tree, so derived files never show up in listings, downloads or quota.
The rest of the backend asks this module by `asset.kind`, never by format.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import orjson

from app.bundle_scan import Finding, apply_report, prompt_injection, report_of
from app.child_process import run_child
from app.collections_io import upload_basename
from app.config import Settings
from app.domain_errors import InvalidInputError, LimitExceededError
from app.models import Asset
from app.pdf_markdown import with_title
from app.services.upload import one_chunk
from app.storage import Storage, read_all, storage_from_url


@dataclass(frozen=True)
class DocumentType:
    kind: str
    # Derived file names: `{stem}.json` and `{stem}.md`.
    stem: str
    # Child process entry point (`python -m {module} {child_args}`).
    module: str
    extensions: tuple[str, ...]
    not_editable_code: str
    wrong_file_code: str
    too_large_code: str
    failed_code: str
    # Key of the counts in the doc payload (`pdf`, `document`).
    payload_key: str
    # The doc payload carries the converted text as `html` (Office): the
    # viewer shows it, so a document held for review is withheld like bytes.
    # False when the browser renders the original itself (PDF.js).
    inline_html: bool
    # First heading of the Markdown when the asset has no title.
    untitled: str
    max_bytes: Callable[[Settings], int]
    timeout: Callable[[Settings], float]
    child_args: Callable[[Settings], list[str]]
    # Cheap parent-side check before a child is started: an error code or None.
    precheck: Callable[[bytes], str | None]
    # Markdown body, search blob and the meta fields kept beyond the common ones.
    body: Callable[[dict[str, Any]], str]
    search_text: Callable[[dict[str, Any]], str | None]
    meta: Callable[[dict[str, Any]], dict[str, Any]]
    # Counts shown in the doc payload and file-mcp, from the meta.
    summary: Callable[[dict[str, Any]], dict[str, Any]]
    # OCR of pages without a text layer (ADR-0021); None when it does not apply.
    ocr: OcrSupport | None = None


@dataclass(frozen=True)
class RecognizedPages:
    """An OCR result: `{page number: text}`; `markdown` when the engine
    returns Markdown (tables, lists) rather than plain lines."""

    texts: dict[int, str]
    markdown: bool = False


@dataclass(frozen=True)
class OcrSupport:
    # Merges an OCR result into an extraction.
    overlay: Callable[[dict[str, Any], RecognizedPages], dict[str, Any]]
    # Pages of a meta that have no text layer, the ones OCR reads on its own.
    pages_without_text: Callable[[dict[str, Any]], int]
    # Pages of a meta whose text is an invisible layer saved over a scan: OCR
    # is recommended and replaces it only on request.
    pages_with_hidden_text: Callable[[dict[str, Any]], int]
    # Pages of a meta whose text came from an earlier OCR run: a new run
    # reads them again (a poor result, a better engine).
    pages_with_ocr_text: Callable[[dict[str, Any]], int]
    # Pages (1-based) of an extraction a run reads: those without text and,
    # with `replace_hidden`, the scans with a saved invisible layer.
    targets: Callable[[dict[str, Any], bool], list[int]]


_TYPES: dict[str, DocumentType] = {}


def register(doc_type: DocumentType) -> DocumentType:
    _TYPES[doc_type.kind] = doc_type
    return doc_type


def document_type(kind: str) -> DocumentType:
    return _TYPES[kind]


def is_document(kind: str) -> bool:
    return kind in _TYPES


def supports_ocr(kind: str) -> bool:
    """Whether OCR applies to `kind`: only scanned formats, never text."""
    return kind in _TYPES and _TYPES[kind].ocr is not None


def renders_inline(kind: str) -> bool:
    """Whether the doc payload of `kind` carries its content as `html`."""
    return kind in _TYPES and _TYPES[kind].inline_html


def derived_prefix(storage_prefix: str, version: int) -> str:
    return f"{storage_prefix}/derived/v{version}"


def filename(kind: str, raw: str | None) -> str:
    """Storage name of an uploaded document: its last path segment, which
    must carry one of the type's extensions. Browsers send a basename,
    other clients may not."""
    doc_type = document_type(kind)
    if not raw or not raw.lower().endswith(doc_type.extensions):
        raise InvalidInputError(
            doc_type.wrong_file_code, f"accepted files: {', '.join(doc_type.extensions)}"
        )
    return upload_basename(raw)


def assert_size(kind: str, size: int, settings: Settings) -> None:
    doc_type = document_type(kind)
    limit = doc_type.max_bytes(settings)
    if size > limit:
        raise LimitExceededError(
            doc_type.too_large_code, f"file too large (size={size}, max={limit})"
        )


async def run_extraction(kind: str, data: bytes, settings: Settings) -> dict[str, Any]:
    """Parse `data` in a child process; raise a domain error on failure."""
    doc_type = document_type(kind)
    code = doc_type.precheck(data)
    if code is not None:
        raise InvalidInputError(code, "the file content does not match its type")
    try:
        out = await run_child(
            doc_type.module, doc_type.child_args(settings), data, doc_type.timeout(settings)
        )
    except TimeoutError:
        raise InvalidInputError(doc_type.failed_code, "reading the file took too long") from None
    if out is None:
        raise InvalidInputError(doc_type.failed_code, "the file could not be read")
    result: dict[str, Any] = orjson.loads(out)
    if not result.get("ok"):
        raise InvalidInputError(
            result.get("code", doc_type.failed_code), result.get("detail", "unreadable file")
        )
    return result


async def ingest(
    storage: Storage,
    *,
    kind: str,
    storage_prefix: str,
    version: int,
    entry_path: str,
    settings: Settings,
    data: bytes | None = None,
    extraction: dict[str, Any] | None = None,
    recognized: RecognizedPages | None = None,
) -> dict[str, Any]:
    """Convert one version and store its derived files. Returns the full
    extraction plus the bytes of both derived files (`meta_json`, `text_md`).
    `recognized` OCR pages are merged into the text, so a rebuild keeps them."""
    doc_type = document_type(kind)
    if extraction is None:
        if data is None:
            data = await read_all(storage, f"{storage_prefix}/v{version}/{entry_path}")
        extraction = await run_extraction(kind, data, settings)
    if recognized and recognized.texts and doc_type.ocr is not None:
        extraction = doc_type.ocr.overlay(extraction, recognized)
    meta = {
        "entry_path": entry_path,
        "findings": extraction["findings"],
        "truncated": extraction["truncated"],
        **doc_type.meta(extraction),
    }
    meta_json, text_md = orjson.dumps(meta), doc_type.body(extraction).encode()
    base = derived_prefix(storage_prefix, version)
    await asyncio.gather(
        storage.put(f"{base}/{doc_type.stem}.json", one_chunk(meta_json)),
        storage.put(f"{base}/{doc_type.stem}.md", one_chunk(text_md)),
    )
    return {**extraction, **meta, "meta_json": meta_json, "text_md": text_md}


def ocr_result_key(storage_prefix: str, version: int) -> str:
    """Where the OCR run of a version keeps its recognized text: next to the
    derived files, but never rebuilt from the document (it is not derivable
    without running OCR again)."""
    return f"{derived_prefix(storage_prefix, version)}/ocr.json"


async def load_ocr_pages(
    storage: Storage, storage_prefix: str, version: int
) -> RecognizedPages | None:
    """The OCR result of a version, None when it has none."""
    try:
        raw = await read_all(storage, ocr_result_key(storage_prefix, version))
    except FileNotFoundError:
        return None
    if not _is_json(raw):
        return None
    result = orjson.loads(raw)
    pages = result.get("pages") or {}
    return RecognizedPages(
        texts={int(number): str(text) for number, text in pages.items()},
        markdown=result.get("format") == "markdown",
    )


def pages_without_text(kind: str, meta: dict[str, Any]) -> int:
    ocr = document_type(kind).ocr
    return ocr.pages_without_text(meta) if ocr is not None else 0


def pages_with_hidden_text(kind: str, meta: dict[str, Any]) -> int:
    ocr = document_type(kind).ocr
    return ocr.pages_with_hidden_text(meta) if ocr is not None else 0


def pages_with_ocr_text(kind: str, meta: dict[str, Any]) -> int:
    ocr = document_type(kind).ocr
    return ocr.pages_with_ocr_text(meta) if ocr is not None else 0


async def load_meta(asset: Asset, version: int, settings: Settings) -> dict[str, Any]:
    """Counts, findings and type-specific fields of one version (see `ingest`)."""
    return orjson.loads(await _derived(asset, version, settings, "meta_json"))


async def markdown(asset: Asset, version: int, settings: Settings) -> str:
    """The Markdown MCP clients read: the current title, then the body."""
    body = await body_markdown(asset, version, settings)
    return with_title(asset.title, body, untitled=document_type(asset.kind).untitled)


async def body_markdown(asset: Asset, version: int, settings: Settings) -> str:
    """The Markdown body without the title line (the viewer shows the title)."""
    return (await _derived(asset, version, settings, "text_md")).decode()


def summary_of(kind: str, meta: dict[str, Any]) -> dict[str, Any]:
    return document_type(kind).summary(meta)


def search_content_of(kind: str, extraction: dict[str, Any]) -> str | None:
    return document_type(kind).search_text(extraction)


async def apply_scan(asset: Asset, settings: Settings) -> dict[str, Any]:
    """Store the current version's findings through the HTML scanner's
    `apply_report`, so the admin queue, the publication gate and the
    findings UI treat a document like a bundle."""
    meta = await load_meta(asset, asset.version, settings)
    findings = [
        Finding(severity=f["severity"], rule=f["rule"], file=meta["entry_path"], line=None)
        for f in meta["findings"]
    ]
    # Extracted text reaches agents like Markdown does, so it gets the same
    # advisory prompt-injection rule; the text is the derived file, not a parse.
    text = await markdown(asset, asset.version, settings)
    findings += await asyncio.to_thread(
        prompt_injection.scan_text, meta["entry_path"], text, with_lines=False
    )
    return apply_report(asset, report_of(findings))


_DERIVED_EXT = {"meta_json": "json", "text_md": "md"}


async def _derived(asset: Asset, version: int, settings: Settings, name: str) -> bytes:
    """A derived file, rebuilt from the stored document when it is missing or
    unreadable. The rebuilt bytes come from memory, not a read back: a
    concurrent rebuild may be truncating the file on the FS backend."""
    doc_type = document_type(asset.kind)
    ext = _DERIVED_EXT[name]
    storage = storage_from_url(settings.storage_url)
    key = f"{derived_prefix(asset.storage_prefix, version)}/{doc_type.stem}.{ext}"
    try:
        raw = await read_all(storage, key)
        if raw and (ext != "json" or _is_json(raw)):
            return raw
    except FileNotFoundError:
        pass
    from app.services.versions import entry_path_at_version  # avoid import cycle

    entry = await entry_path_at_version(asset, version, settings)
    if entry is None:
        raise FileNotFoundError(f"v{version} has no document")
    recognized = (
        await load_ocr_pages(storage, asset.storage_prefix, version) if doc_type.ocr else None
    )
    rebuilt = await ingest(
        storage,
        kind=asset.kind,
        storage_prefix=asset.storage_prefix,
        version=version,
        entry_path=entry,
        settings=settings,
        recognized=recognized,
    )
    data: bytes = rebuilt[name]
    return data


def _is_json(raw: bytes) -> bool:
    try:
        orjson.loads(raw)
    except orjson.JSONDecodeError:
        return False
    return True


# The document types register themselves on import; importing them here
# means every user of this module sees the full registry.
from app.services import office_assets, pdf_assets  # noqa: E402, F401
