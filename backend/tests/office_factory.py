"""Build small Word and ODF documents for tests, without binary fixtures.

`make_docx` and `make_odt` write the minimal ZIP packages the formats
need; `make_doc` writes a Word 97-2003 file: an OLE compound file (CFB v3,
no mini stream) with a `WordDocument` stream holding the FIB and the text,
and a `1Table` stream holding the piece table.

Blocks for docx/odt: ("h1".."h3", text), ("p", text), ("li", text),
("table", [[cell, ...], ...]), ("img",), ("fn", text, note).
docx only: ("title", text), ("subtitle", text), styled with the ids Polish Word writes.
"""

from __future__ import annotations

import io
import struct
import zipfile
from collections.abc import Sequence
from html import escape
from typing import Any

Block = tuple[Any, ...]

_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)


# ---------- docx ----------

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_RT = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _run(text: str) -> str:
    return f'<w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def _image_run() -> str:
    return (
        "<w:r><w:drawing><wp:inline "
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">'
        '<wp:extent cx="9525" cy="9525"/><wp:docPr id="1" name="Picture 1" descr="a chart"/>'
        '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:nvPicPr><pic:cNvPr id="1" name="image1.png"/><pic:cNvPicPr/></pic:nvPicPr>'
        '<pic:blipFill><a:blip r:embed="rIdImg"/></pic:blipFill>'
        "<pic:spPr/></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r>"
    )


# Block kind -> (style id, style name).
_DOCX_LOCALIZED_STYLES = {"title": ("Tytu", "Title"), "subtitle": ("Podtytu", "Subtitle")}


def _docx_block(block: Block) -> str:
    kind = block[0]
    if kind in ("h1", "h2", "h3"):
        style = f"Heading{kind[1]}"
        return f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr>{_run(block[1])}</w:p>'
    if kind in _DOCX_LOCALIZED_STYLES:
        style = _DOCX_LOCALIZED_STYLES[kind][0]
        return f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr>{_run(block[1])}</w:p>'
    if kind == "p":
        return f"<w:p>{_run(block[1])}</w:p>"
    if kind == "li":
        return (
            '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr>'
            f"{_run(block[1])}</w:p>"
        )
    if kind == "table":
        rows = "".join(
            "<w:tr>" + "".join(f"<w:tc><w:p>{_run(c)}</w:p></w:tc>" for c in row) + "</w:tr>"
            for row in block[1]
        )
        return f"<w:tbl>{rows}</w:tbl>"
    if kind == "img":
        return f"<w:p>{_image_run()}</w:p>"
    if kind == "fn":
        return f'<w:p>{_run(block[1])}<w:r><w:footnoteReference w:id="1"/></w:r></w:p>'
    raise ValueError(kind)


def make_docx(
    blocks: Sequence[Block],
    *,
    macros: bool = False,
    embedded: bool = False,
    remote_template: str | None = None,
    local_template: str | None = None,
) -> bytes:
    notes = [b[2] for b in blocks if b[0] == "fn"]
    body = "".join(_docx_block(b) for b in blocks)
    document = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{_W}" xmlns:r="{_R}"><w:body>{body}</w:body></w:document>'
    )
    styles = (
        f'<w:styles xmlns:w="{_W}">'
        + "".join(
            f'<w:style w:type="paragraph" w:styleId="Heading{n}"><w:name w:val="heading {n}"/></w:style>'
            for n in (1, 2, 3)
        )
        + "".join(
            f'<w:style w:type="paragraph" w:styleId="{sid}"><w:name w:val="{name}"/></w:style>'
            for sid, name in _DOCX_LOCALIZED_STYLES.values()
        )
        + "</w:styles>"
    )
    numbering = (
        f'<w:numbering xmlns:w="{_W}"><w:abstractNum w:abstractNumId="0">'
        '<w:lvl w:ilvl="0"><w:numFmt w:val="bullet"/><w:lvlText w:val="*"/></w:lvl>'
        '</w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>'
    )
    rels = [
        f'<Relationship Id="rIdStyles" Type="{_RT}/styles" Target="styles.xml"/>',
        f'<Relationship Id="rIdNum" Type="{_RT}/numbering" Target="numbering.xml"/>',
        f'<Relationship Id="rIdImg" Type="{_RT}/image" Target="media/image1.png"/>',
    ]
    files: dict[str, bytes | str] = {
        "[Content_Types].xml": (
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Default Extension="png" ContentType="image/png"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            f'<Relationships xmlns="{_REL}"><Relationship Id="rId1" '
            f'Type="{_RT}/officeDocument" Target="word/document.xml"/></Relationships>'
        ),
        "word/document.xml": document,
        "word/styles.xml": styles,
        "word/numbering.xml": numbering,
        "word/media/image1.png": _PNG,
    }
    if notes:
        rels.append(f'<Relationship Id="rIdFn" Type="{_RT}/footnotes" Target="footnotes.xml"/>')
        files["word/footnotes.xml"] = (
            f'<w:footnotes xmlns:w="{_W}"><w:footnote w:id="1"><w:p>{_run(notes[0])}</w:p>'
            "</w:footnote></w:footnotes>"
        )
    if macros:
        files["word/vbaProject.bin"] = b"\xd0\xcf\x11\xe0 fake vba"
    if embedded:
        files["word/embeddings/oleObject1.bin"] = b"ole"
    settings_rels = []
    if remote_template:
        settings_rels.append(
            f'<Relationship Id="rIdT" Type="{_RT}/attachedTemplate" '
            f'Target="{escape(remote_template)}" TargetMode="External"/>'
        )
    if local_template:
        settings_rels.append(
            f'<Relationship Id="rIdL" Type="{_RT}/attachedTemplate" '
            f'Target="{escape(local_template)}" TargetMode="External"/>'
        )
    if settings_rels:
        files["word/settings.xml"] = f'<w:settings xmlns:w="{_W}"/>'
        files["word/_rels/settings.xml.rels"] = (
            f'<Relationships xmlns="{_REL}">{"".join(settings_rels)}</Relationships>'
        )
        rels.append(f'<Relationship Id="rIdSet" Type="{_RT}/settings" Target="settings.xml"/>')
    files["word/_rels/document.xml.rels"] = (
        f'<Relationships xmlns="{_REL}">{"".join(rels)}</Relationships>'
    )
    return _zip(files)


# ---------- odt ----------

_ODF_NS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
    'xmlns:xlink="http://www.w3.org/1999/xlink"'
)


def _odt_block(block: Block) -> str:
    kind = block[0]
    if kind in ("h1", "h2", "h3"):
        return f'<text:h text:outline-level="{kind[1]}">{escape(block[1])}</text:h>'
    if kind == "p":
        return f"<text:p>{escape(block[1])}</text:p>"
    if kind == "li":
        return f"<text:list><text:list-item><text:p>{escape(block[1])}</text:p></text:list-item></text:list>"
    if kind == "table":
        rows = "".join(
            "<table:table-row>"
            + "".join(
                f"<table:table-cell><text:p>{escape(c)}</text:p></table:table-cell>" for c in row
            )
            + "</table:table-row>"
            for row in block[1]
        )
        return f"<table:table>{rows}</table:table>"
    if kind == "img":
        return '<text:p><draw:frame><draw:image xlink:href="Pictures/a.png"/></draw:frame></text:p>'
    if kind == "fn":
        return (
            f"<text:p>{escape(block[1])}<text:note><text:note-citation>1</text:note-citation>"
            f"<text:note-body><text:p>{escape(block[2])}</text:p></text:note-body></text:note></text:p>"
        )
    raise ValueError(kind)


def make_odt(
    blocks: Sequence[Block],
    *,
    macros: bool = False,
    encrypted: bool = False,
    embedded: bool = False,
    link: tuple[str, str] | None = None,
) -> bytes:
    body = "".join(_odt_block(b) for b in blocks)
    if link:
        body += (
            f'<text:p><text:a xlink:href="{escape(link[1])}">{escape(link[0])}</text:a></text:p>'
        )
    content = (
        f'<?xml version="1.0" encoding="UTF-8"?><office:document-content {_ODF_NS}>'
        f"<office:body><office:text>{body}</office:text></office:body></office:document-content>"
    )
    manifest = (
        '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0">'
    )
    if encrypted:
        manifest += "<manifest:file-entry><manifest:encryption-data/></manifest:file-entry>"
    manifest += "</manifest:manifest>"
    files: dict[str, bytes | str] = {
        "mimetype": "application/vnd.oasis.opendocument.text",
        "content.xml": content,
        "META-INF/manifest.xml": manifest,
        "Pictures/a.png": _PNG,
    }
    if macros:
        files["Basic/Standard/Module1.xml"] = "<script/>"
    if embedded:
        files["Object 1/content.xml"] = "<x/>"
    return _zip(files)


def _zip(files: dict[str, bytes | str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            method = zipfile.ZIP_STORED if name == "mimetype" else zipfile.ZIP_DEFLATED
            zf.writestr(name, data, compress_type=method)
    return buf.getvalue()


def zip_bomb(declared_bytes: int) -> bytes:
    """A .docx-looking archive whose content unpacks to `declared_bytes`."""
    return _zip(
        {
            "word/document.xml": "<w:document/>",
            "word/filler.bin": b"\0" * declared_bytes,
        }
    )


# ---------- doc (Word 97-2003) ----------

_END, _FREE, _FATSECT, _NOSTREAM = 0xFFFFFFFE, 0xFFFFFFFF, 0xFFFFFFFD, 0xFFFFFFFF
_SECTOR = 512
_TEXT_AT = 1024


def doc_text(
    paragraphs: Sequence[str] = (), rows: Sequence[Sequence[str]] = (), trailer: Sequence[str] = ()
) -> str:
    """Word's raw text: paragraphs end with \\r, a table cell with \\x07 and
    a row with an extra \\x07."""
    text = "".join(f"{p}\r" for p in paragraphs)
    text += "".join("".join(f"{c}\x07" for c in row) + "\x07" for row in rows)
    text += "".join(f"{p}\r" for p in trailer)
    return text


def _sttb(strings: Sequence[str]) -> bytes:
    """An extended STTB (UTF-16 strings, no extra data)."""
    out = struct.pack("<HHH", 0xFFFF, len(strings), 0)
    for item in strings:
        out += struct.pack("<H", len(item)) + item.encode("utf-16-le")
    return out


def _word_document(
    text: str, *, encrypted: bool, compressed: bool, template: str | None = None
) -> tuple[bytes, bytes]:
    wd = bytearray(_TEXT_AT)
    struct.pack_into("<HH", wd, 0, 0xA5EC, 0x00C1)
    flags = 0x0200 | (0x0100 if encrypted else 0)
    struct.pack_into("<H", wd, 0x0A, flags)
    struct.pack_into("<H", wd, 32, 14)  # csw
    struct.pack_into("<H", wd, 62, 22)  # cslw
    struct.pack_into("<I", wd, 64 + 3 * 4, len(text))  # ccpText
    struct.pack_into("<H", wd, 152, 93)  # cbRgFcLcb
    if compressed:
        wd += text.encode("cp1252")
        fc = (_TEXT_AT * 2) | 0x40000000
    else:
        wd += text.encode("utf-16-le")
        fc = _TEXT_AT
    plc = struct.pack("<II", 0, len(text)) + struct.pack("<HIH", 0, fc, 0)
    clx = b"\x02" + struct.pack("<I", len(plc)) + plc
    struct.pack_into("<II", wd, 154 + 33 * 8, 0, len(clx))  # fcClx, lcbClx
    table = clx
    if template is not None:
        assoc = _sttb(["", template])  # ibstAssocDot is entry 1
        struct.pack_into("<II", wd, 154 + 32 * 8, len(clx), len(assoc))  # fcSttbfAssoc
        table += assoc
    return bytes(wd), table


def _pad(data: bytes) -> bytes:
    # At least 4096 bytes keeps every stream out of the mini stream.
    size = max(4096, -(-len(data) // _SECTOR) * _SECTOR)
    return data + b"\0" * (size - len(data))


def _dir_entry(name: str, kind: int, *, right: int, child: int, start: int, size: int) -> bytes:
    encoded = (name + "\0").encode("utf-16-le")
    return (
        encoded.ljust(64, b"\0")
        + struct.pack("<HBB", len(encoded), kind, 1)
        + struct.pack("<III", _NOSTREAM, right, child)
        + b"\0" * 16
        + struct.pack("<I", 0)
        + b"\0" * 16
        + struct.pack("<II", start, size)
        + b"\0" * 4
    )


def make_ole(streams: dict[str, bytes], storages: Sequence[str] = ()) -> bytes:
    """A CFB v3 file with `streams` (and empty `storages`) under the root."""
    entries = sorted(
        [(n, 2, d) for n, d in streams.items()] + [(n, 1, b"") for n in storages],
        key=lambda e: (len(e[0]), e[0].upper()),
    )
    assert len(entries) <= 3, "one directory sector holds root + 3 entries"
    fat = [_FATSECT, _END]
    sectors: list[bytes] = []
    placed = []
    for name, kind, data in entries:
        if kind == 1:
            placed.append((name, kind, _END, 0))
            continue
        padded = _pad(data)
        start = 2 + len(sectors)
        count = len(padded) // _SECTOR
        fat += [start + i + 1 for i in range(count - 1)] + [_END]
        sectors += [padded[i * _SECTOR : (i + 1) * _SECTOR] for i in range(count)]
        # The recorded size must stay >= 4096 too, or readers look for the
        # stream in the (absent) mini stream.
        placed.append((name, kind, start, len(padded)))
    assert len(fat) <= 128, "one FAT sector"
    directory = _dir_entry("Root Entry", 5, right=_NOSTREAM, child=1, start=_END, size=0)
    for i, (name, kind, start, size) in enumerate(placed, start=1):
        right = i + 1 if i < len(placed) else _NOSTREAM
        child = _NOSTREAM
        directory += _dir_entry(name, kind, right=right, child=child, start=start, size=size)
    directory = directory.ljust(_SECTOR, b"\0")
    # Unused entries must read as empty: type 0 and no siblings.
    unused = (
        b"\0" * 64
        + struct.pack("<HBB", 0, 0, 0)
        + struct.pack("<III", _NOSTREAM, _NOSTREAM, _NOSTREAM)
    ).ljust(128, b"\0")
    used = 128 * (1 + len(placed))
    directory = directory[:used] + unused * ((len(directory) - used) // 128)
    fat_sector = struct.pack(f"<{len(fat)}I", *fat) + struct.pack("<I", _FREE) * (128 - len(fat))
    header = (
        bytes.fromhex("d0cf11e0a1b11ae1")
        + b"\0" * 16
        + struct.pack("<HHHHH", 0x003E, 0x0003, 0xFFFE, 9, 6)
        + b"\0" * 6
        + struct.pack("<IIIIIIIII", 0, 1, 1, 0, 4096, _END, 0, _END, 0)
        + struct.pack("<I", 0)
        + struct.pack("<I", _FREE) * 108
    )
    assert len(header) == _SECTOR
    return header + fat_sector + directory + b"".join(sectors)


def make_doc(
    text: str,
    *,
    encrypted: bool = False,
    compressed: bool = True,
    macros: bool = False,
    template: str | None = None,
) -> bytes:
    word, table = _word_document(
        text, encrypted=encrypted, compressed=compressed, template=template
    )
    return make_ole({"WordDocument": word, "1Table": table}, ["Macros"] if macros else [])


def office_file(name: str, data: bytes) -> dict[str, tuple[str, bytes, str]]:
    """httpx `files=` for the document upload endpoint."""
    return {"file": (name, data, "application/octet-stream")}
