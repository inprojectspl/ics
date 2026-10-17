"""Build small PDFs for tests: text pages, scanned (text-less) pages,
bookmarks, active content and encryption, without binary fixtures."""

from __future__ import annotations

import io
from collections.abc import Sequence

from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    TextStringObject,
)


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _helvetica(writer: PdfWriter, **extra):
    """A Helvetica font object; `extra` adds entries such as `/Widths`."""
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
            **{NameObject(f"/{key}"): value for key, value in extra.items()},
        }
    )
    return writer._add_object(font)


def _set_content(writer: PdfWriter, page, ops: Sequence[str], resources: dict) -> None:
    stream = DecodedStreamObject()
    stream.set_data("\n".join(ops).encode("latin-1"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    page[NameObject("/Resources")] = DictionaryObject(resources)


def _to_bytes(writer: PdfWriter) -> bytes:
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _add_text_page(writer: PdfWriter, lines: Sequence[str], font_ref, scan_ref=None) -> None:
    """A page of text; with `scan_ref` the page is a scan: the image drawn
    over the whole page and the text as an invisible layer (`3 Tr`)."""
    page = writer.add_blank_page(width=612, height=792)
    if not lines:
        return
    ops = ["q 612 0 0 792 0 0 cm /Scan Do Q"] if scan_ref is not None else []
    ops += ["BT", "/F1 12 Tf", "14 TL", "72 720 Td"]
    if scan_ref is not None:
        ops.append("3 Tr")
    for line in lines:
        ops.append(f"({_escape(line)}) Tj T*")
    ops.append("ET")
    resources = {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
    if scan_ref is not None:
        resources[NameObject("/XObject")] = DictionaryObject({NameObject("/Scan"): scan_ref})
    _set_content(writer, page, ops, resources)


def _scan_image(writer: PdfWriter):
    """A 1x1 grey image XObject, enough to stand for a scanned page."""
    image = DecodedStreamObject()
    image.set_data(b"\x80")
    image.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(1),
            NameObject("/Height"): NumberObject(1),
            NameObject("/ColorSpace"): NameObject("/DeviceGray"),
            NameObject("/BitsPerComponent"): NumberObject(8),
        }
    )
    return writer._add_object(image)


def make_pdf(
    pages: Sequence[str | None],
    *,
    bookmarks: Sequence[tuple[str, int, int]] = (),
    javascript: bool = False,
    launch: bool = False,
    embedded: bool = False,
    xfa: bool = False,
    user_password: str | None = None,
    owner_password: str | None = None,
    scanned_text: Sequence[int] = (),
) -> bytes:
    """`pages`: text of each page (lines split on `\\n`), `None` for a page
    without a text layer. `bookmarks`: `(title, page_index, level)`, level 1
    or 2 (a level-2 item nests under the previous level-1 one).
    `scanned_text`: indexes of text pages drawn as a scan with an invisible
    text layer, as a scanner with built-in OCR saves them."""
    writer = PdfWriter()
    font_ref = _helvetica(writer)
    scan_ref = _scan_image(writer) if scanned_text else None
    for index, text in enumerate(pages):
        _add_text_page(
            writer,
            text.split("\n") if text else [],
            font_ref,
            scan_ref if index in scanned_text else None,
        )

    parent = None
    for title, page_index, level in bookmarks:
        item = writer.add_outline_item(title, page_index, parent=parent if level > 1 else None)
        if level == 1:
            parent = item

    if javascript:
        action = DictionaryObject(
            {
                NameObject("/S"): NameObject("/JavaScript"),
                NameObject("/JS"): TextStringObject("app.alert('hi');"),
            }
        )
        names = DictionaryObject(
            {
                NameObject("/Names"): ArrayObject(
                    [TextStringObject("js"), writer._add_object(action)]
                )
            }
        )
        writer._root_object[NameObject("/Names")] = DictionaryObject(
            {NameObject("/JavaScript"): writer._add_object(names)}
        )
    if launch:
        action = DictionaryObject(
            {
                NameObject("/S"): NameObject("/Launch"),
                NameObject("/F"): TextStringObject("calc.exe"),
            }
        )
        writer._root_object[NameObject("/OpenAction")] = writer._add_object(action)
    if embedded:
        writer.add_attachment("notes.txt", b"attached")
    if xfa:
        writer._root_object[NameObject("/AcroForm")] = DictionaryObject(
            {NameObject("/Fields"): ArrayObject(), NameObject("/XFA"): ArrayObject()}
        )
    if user_password is not None or owner_password is not None:
        writer.encrypt(
            user_password=user_password or "",
            owner_password=owner_password,
            algorithm="AES-128",
        )
    return _to_bytes(writer)


# Helvetica advance widths (1/1000 em) of the lowercase letters.
_HELVETICA = dict(
    zip(
        "abcdefghijklmnopqrstuvwxyz",
        map(
            int,
            "556 556 500 556 556 278 556 556 222 222 500 222 833 "
            "556 556 556 556 333 500 278 556 500 722 500 500 500".split(),
        ),
        strict=True,
    )
)


def make_glyph_placed_pdf(text: str) -> bytes:
    """One page of lowercase `text` drawn the way some producers (scanner
    software among them) save it: every glyph at its own position, no space
    characters, and a font whose declared widths are far too narrow, so a
    parser that trusts the widths sees a gap after every letter."""
    writer = PdfWriter()
    font_ref = _helvetica(
        writer,
        FirstChar=NumberObject(32),
        LastChar=NumberObject(126),
        Widths=ArrayObject([NumberObject(100)] * 95),
    )
    page = writer.add_blank_page(width=612, height=792)
    ops = ["BT", "/F1 1 Tf", "12 0 0 12 72 720 Tm"]
    for word in text.split():
        ops += [f"({char}) Tj {_HELVETICA[char] / 1000 + 0.03} 0 Td" for char in word]
        ops.append("0.3 0 Td")
    ops.append("ET")
    _set_content(
        writer, page, ops, {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
    )
    return _to_bytes(writer)


def pdf_file(name: str, data: bytes) -> dict[str, tuple[str, bytes, str]]:
    """httpx `files=` for the single-PDF upload endpoint."""
    return {"file": (name, data, "application/pdf")}
