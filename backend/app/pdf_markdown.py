"""Markdown and search text built from a PDF extraction (`pdf_extract`).

One `## Page N` section per page, so line ranges, outline headings and search hits
all point at a page; a page without text gets a note, not an empty section.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Sequence

# Pages are separated by a form feed in the search blob: it is whitespace
# for the FTS parser and lets a snippet be mapped back to its page.
PAGE_SEPARATOR = "\n\f\n"
NO_TEXT_NOTE = "_No text layer on this page (scanned image?)._"
TRUNCATED_NOTE = "_Text of this page was not extracted: the document exceeds the extraction limit._"
# A page read by OCR (ADR-0021): the text may contain recognition errors.
OCR_NOTE = "_Text recognized by OCR._"
OCR_BLANK_NOTE = "_No text layer on this page; OCR found no text._"

# Line starts that Markdown would turn into structure (headings, quotes,
# lists, rules, HTML). Extracted text is prose, so they are escaped.
_MD_LINE_START = re.compile(r"^(\s*)([#>*+=|<-]|\d+[.)]\s)")


def escape_line(line: str) -> str:
    return _MD_LINE_START.sub(lambda m: f"{m.group(1)}\\{m.group(2)}", line)


# OCR engines that return Markdown (tables, lists) keep it, except what
# would break the `## Page N` structure or point at nothing: headings become
# bold, setext underlines and image references go, raw HTML is escaped.
_MD_HEADING = re.compile(r"^\s*#{1,6}\s+(.+?)\s*#*\s*$")
_MD_SETEXT = re.compile(r"^\s*(-{3,}|={3,}|\*{3,}|_{3,})\s*$")
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_HTML = re.compile(r"^(\s*)<")


def ocr_markdown_lines(text: str) -> str:
    """Markdown from an OCR engine, made safe to sit inside a page section."""
    out = []
    for line in text.split("\n"):
        line = _MD_IMAGE.sub("", line)
        if _MD_SETEXT.match(line):
            continue
        heading = _MD_HEADING.match(line)
        if heading:
            line = f"**{heading.group(1)}**"
        out.append(_MD_HTML.sub(lambda m: f"{m.group(1)}\\<", line))
    return "\n".join(out).strip()


def pages_markdown(
    pages: Sequence[str | None], ocr_pages: Collection[int] = (), *, ocr_markdown: bool = False
) -> str:
    """The page sections, without the title (renameable after extraction).

    `pages`: text, `""` for no text layer, `None` past the extraction limit.
    `ocr_pages` (1-based) get a note that OCR text may be imperfect."""
    parts = []
    for number, text in enumerate(pages, start=1):
        parts.append(f"## Page {number}")
        if number in ocr_pages:
            parts.append(OCR_NOTE if text else OCR_BLANK_NOTE)
        if text and ocr_markdown and number in ocr_pages:
            parts.append(ocr_markdown_lines(text))
        elif text:
            parts.append("\n".join(escape_line(line) for line in text.split("\n")))
        elif number not in ocr_pages:
            parts.append(TRUNCATED_NOTE if text is None else NO_TEXT_NOTE)
    return "\n\n".join(parts)


def with_title(title: str | None, body: str, *, untitled: str = "PDF document") -> str:
    heading = f"# {title.strip()}" if title and title.strip() else f"# {untitled}"
    return f"{heading}\n\n{body}\n" if body else f"{heading}\n"


def pdf_to_markdown(title: str | None, pages: Sequence[str | None]) -> str:
    return with_title(title, pages_markdown(pages))


def search_text(pages: Sequence[str | None]) -> str | None:
    """The `search_content` blob: page texts in order, form-feed separated."""
    if not any(pages):
        return None
    return PAGE_SEPARATOR.join(text or "" for text in pages)


def snippet_probe(snippet: str, *, start_sel: str, stop_sel: str) -> tuple[str, str] | None:
    """`(regex, bare term)` to find a snippet's page in `search_content`, from the
    first highlight on (the fragment may start in the title); the regex allows any
    whitespace, as a phrase may cross a page break. None without a highlight."""
    marked = snippet.find(start_sel)
    if marked < 0:
        return None
    tail = snippet[marked:].split("...")[0].replace(start_sel, "").replace(stop_sel, "")
    words = tail.split()[:4]
    if not words:
        return None
    return r"\s+".join(re.escape(w) for w in words), words[0]
