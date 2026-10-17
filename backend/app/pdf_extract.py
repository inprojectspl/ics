"""Text, outline and active-content extraction from an uploaded PDF.

Runs as a child process (`python -m app.pdf_extract`, PDF on stdin, JSON on
stdout) because a crafted PDF can make pypdf loop or balloon and only a process
can be killed; so it imports nothing from `app` and takes limits as arguments.
"""

from __future__ import annotations

import io
import json
import logging
import re
import sys
from typing import Any

PDF_MAGIC = b"%PDF-"
# The PDF spec allows junk before the header; readers accept it within 1 KB.
MAGIC_WINDOW = 1024

# Bound the object walk of the scan: a real document has at most tens of
# thousands of objects, a hostile one can reference millions.
_SCAN_MAX_OBJECTS = 200_000
_MAX_BOOKMARKS = 2_000
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# A text layer saved over a scan (by the scanner or an OCR tool) is drawn
# invisible (`3 Tr`) on top of a page-sized image placed by `a 0 0 d e f cm
# /Name Do`. Read from the page's own content stream.
_TEXT_RENDER_MODE = re.compile(rb"(\d)\s+Tr\b")
_IMAGE_PLACEMENT = re.compile(
    rb"(-?[\d.]+)\s+0\s+0\s+(-?[\d.]+)\s+-?[\d.]+\s+-?[\d.]+\s+cm\s*/([^\s/\[\]<>()]+)\s+Do"
)
# Share of the page an image must cover to count as the scan of the page.
_SCAN_COVERAGE = 0.8
_BLANK_RUN = re.compile(r"\n{3,}")
# Some producers place every glyph on its own and draw no space characters;
# pypdf then guesses word breaks from glyph widths and returns letter-spaced
# text ("S é cu rité d e s"). A page counts as such when most of its words
# are one or two letters long (numbers do not count: tables are full of them).
_WORD = re.compile(r"[^\W\d_]+")
_SPACED_MIN_WORDS = 20
_SPACED_SHORT_SHARE = 0.6
# A gap between two glyphs wider than this share of the glyph height is a
# word break (measured on letter-spaced documents: letters sit under 0.15,
# words above 0.3).
_WORD_GAP = 0.2


def has_pdf_signature(head: bytes) -> bool:
    return PDF_MAGIC in head[:MAGIC_WINDOW]


def clean_text(text: str) -> str:
    """Normalize extracted page text: no control characters, no trailing
    spaces, at most one blank line in a row."""
    text = _CONTROL_CHARS.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    lines = [line.rstrip() for line in text.split("\n")]
    return _BLANK_RUN.sub("\n\n", "\n".join(lines)).strip()


def is_letter_spaced(text: str) -> bool:
    words = _WORD.findall(text)
    if len(words) < _SPACED_MIN_WORDS:
        return False
    return sum(len(w) <= 2 for w in words) / len(words) > _SPACED_SHORT_SHARE


def text_from_glyph_positions(page: Any) -> str:
    """Page text with word breaks placed from glyph positions (pdfium),
    for pages whose producer drew no space characters."""
    import pypdfium2.raw as pdfium_raw

    textpage = page.get_textpage()
    try:
        out: list[str] = []
        prev_right: float | None = None
        prev_bottom = prev_height = 0.0
        for index in range(textpage.count_chars()):
            # One call per glyph, keeping char indexes aligned (the page's
            # text string may not be).
            char = chr(pdfium_raw.FPDFText_GetUnicode(textpage.raw, index))
            if char == " " and pdfium_raw.FPDFText_IsGenerated(textpage.raw, index) == 1:
                # pdfium guesses these from the same font widths pypdf trusts.
                continue
            if char.isspace():
                # pdfium ends a line with "\r\n"; keep one newline.
                if char != "\r":
                    out.append("\n" if char == "\n" else " ")
                prev_right = None
                continue
            left, _, right, _ = textpage.get_charbox(index)
            # The loose box spans the font's ascent and descent: a steady
            # size measure, unlike the tight box of "x" or "l".
            _, bottom, _, top = textpage.get_charbox(index, loose=True)
            height = top - bottom
            if prev_right is not None:
                em = max(height, prev_height)
                if abs(bottom - prev_bottom) > em / 2:
                    out.append("\n")
                elif left - prev_right > _WORD_GAP * em:
                    out.append(" ")
            out.append(char)
            prev_right, prev_bottom, prev_height = right, bottom, height
        return clean_text("".join(out))
    finally:
        textpage.close()
        page.close()


class _Pdfium:
    """The document in pdfium, opened on the first letter-spaced page."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._doc: Any = None

    def respaced(self, index: int, text: str) -> str:
        try:
            if self._doc is None:
                import pypdfium2 as pdfium

                self._doc = pdfium.PdfDocument(self._data)
            return text_from_glyph_positions(self._doc[index]) or text
        except Exception:
            # Keep pypdf's text: spaced out, but still searchable.
            return text

    def close(self) -> None:
        if self._doc is not None:
            self._doc.close()


def failure(code: str, detail: str) -> dict[str, Any]:
    """The failure result the parent turns into a domain error."""
    return {"ok": False, "code": code, "detail": detail}


def _open(data: bytes) -> Any:
    """Parsed reader, or a failure dict for a file that is not a readable PDF."""
    from pypdf import PasswordType, PdfReader

    if not has_pdf_signature(data):
        return failure("invalid_pdf", "the file has no PDF signature")
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted and reader.decrypt("") == PasswordType.NOT_DECRYPTED:
            # Owner-password-only files open with an empty user password;
            # these do not, so the text is unreachable without the password.
            return failure("pdf_encrypted", "the PDF is protected with a password")
        len(reader.pages)
    except Exception as exc:
        return failure("invalid_pdf", f"the PDF cannot be parsed: {type(exc).__name__}")
    return reader


def _bookmarks(reader: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def walk(items: list[Any], level: int) -> None:
        for item in items:
            if len(out) >= _MAX_BOOKMARKS:
                return
            if isinstance(item, list):
                walk(item, level + 1)
                continue
            try:
                page = reader.get_destination_page_number(item)
            except Exception:
                page = None
            title = clean_text(str(getattr(item, "title", "") or ""))
            if title:
                out.append(
                    {"level": level, "title": title, "page": None if page is None else page + 1}
                )

    try:
        walk(reader.outline, 1)
    except Exception:
        # A broken outline tree is not a reason to reject the document.
        return out
    return out


def has_hidden_text_over_scan(page: Any) -> bool:
    """Whether the page is a scan (an image over `_SCAN_COVERAGE`) under only
    invisible text: third-party OCR of unknown quality, so ours can be offered."""
    try:
        data = page.get_contents().get_data()
        if set(_TEXT_RENDER_MODE.findall(data)) != {b"3"}:
            return False
        xobjects = page["/Resources"].get_object().get("/XObject")
        xobjects = xobjects.get_object() if xobjects is not None else {}
        box = page.mediabox
        area = float(box.width) * float(box.height)
        for a, d, name in _IMAGE_PLACEMENT.findall(data):
            ref = xobjects.get(f"/{name.decode('latin-1')}")
            if ref is None or ref.get_object().get("/Subtype") != "/Image":
                continue
            if area > 0 and abs(float(a) * float(d)) >= _SCAN_COVERAGE * area:
                return True
    except Exception:
        return False
    return False


def scan_active_content(reader: Any) -> list[dict[str, str]]:
    """Find content a PDF reader could execute or unpack: JavaScript, launch
    actions, embedded files and XFA forms. Walks the object graph from the
    catalog, so compressed object streams are covered (a byte grep is not)."""
    from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, NameObject

    found: dict[str, str] = {}
    seen: set[tuple[int, int]] = set()
    stack: list[Any] = [reader.trailer.get("/Root")]
    visited = 0
    while stack and visited < _SCAN_MAX_OBJECTS:
        node = stack.pop()
        if isinstance(node, IndirectObject):
            ref = (node.idnum, node.generation)
            if ref in seen:
                continue
            seen.add(ref)
            try:
                node = node.get_object()
            except Exception:
                continue
        visited += 1
        if isinstance(node, DictionaryObject):
            subtype = node.get("/S")
            if "/JS" in node or subtype == NameObject("/JavaScript") or "/JavaScript" in node:
                found.setdefault("pdf_javascript", "warn")
            if subtype == NameObject("/Launch"):
                found["pdf_launch_action"] = "critical"
            if "/EmbeddedFiles" in node or node.get("/Type") == NameObject("/EmbeddedFile"):
                found.setdefault("pdf_embedded_file", "warn")
            if "/XFA" in node:
                found.setdefault("pdf_xfa_form", "warn")
            # `/Parent` only leads back up the page tree already on the stack.
            stack.extend(v for k, v in node.items() if k != "/Parent")
        elif isinstance(node, ArrayObject):
            stack.extend(node)
    return [{"rule": rule, "severity": severity} for rule, severity in sorted(found.items())]


def extract_pdf(data: bytes, *, max_pages: int, max_chars: int) -> dict[str, Any]:
    """Extract everything ICS stores about a PDF. Pages past `max_pages` or
    past `max_chars` of text in total get `None` (not extracted, unlike `""`
    for a page without text) and set `truncated`."""
    reader = _open(data)
    if isinstance(reader, dict):
        return reader
    # pypdf reports recoverable damage through `logging`; the parent reads
    # only stdout, so keep stderr quiet instead of filling the pipe.
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    page_count = len(reader.pages)
    pages: list[str | None] = []
    hidden: list[int] = []
    pdfium = _Pdfium(data)
    used = 0
    truncated = False
    for index in range(page_count):
        if index >= max_pages or used >= max_chars:
            truncated = True
            pages.append(None)
            continue
        try:
            text = clean_text(reader.pages[index].extract_text() or "")
        except Exception:
            text = ""
        if is_letter_spaced(text):
            text = pdfium.respaced(index, text)
        if used + len(text) > max_chars:
            text = text[: max_chars - used]
            truncated = True
        used += len(text)
        pages.append(text)
        if text and has_hidden_text_over_scan(reader.pages[index]):
            hidden.append(index + 1)
    pdfium.close()
    return {
        "ok": True,
        "page_count": page_count,
        "pages": pages,
        "hidden_text_pages": hidden,
        "bookmarks": _bookmarks(reader),
        "findings": scan_active_content(reader),
        "truncated": truncated,
    }


def limit_resources(memory_bytes: int) -> None:
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    except (ImportError, ValueError, OSError):
        # Not every platform allows lowering the address space (macOS);
        # the parent's timeout still bounds the run.
        pass


def main(argv: list[str]) -> int:
    max_pages, max_chars, memory_bytes = (int(a) for a in argv)
    limit_resources(memory_bytes)
    data = sys.stdin.buffer.read()
    try:
        result = extract_pdf(data, max_pages=max_pages, max_chars=max_chars)
    except MemoryError:
        result = failure("pdf_extraction_failed", "the PDF needs too much memory")
    sys.stdout.write(json.dumps(result))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the subprocess
    raise SystemExit(main(sys.argv[1:]))
