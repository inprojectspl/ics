"""Text of a Word 97-2003 `.doc` through its piece table ([MS-DOC] 2.4.1).

Part of the Office converter child process (`app.office_extract`): pure,
no settings. Styles are not parsed, so the result has paragraphs and table
rows but no heading levels (ADR-0014).
"""

from __future__ import annotations

import html
import re
import struct
from typing import Any

from app.html_markdown import html_to_markdown
from app.pdf_extract import failure
from app.pdf_markdown import escape_line

IMAGE_MARKER = "[image]"


def is_remote(target: str) -> bool:
    """Whether an editor fetches `target` over the network: http(s), a UNC
    path, or `file://host/...`. A UNC or `file://host` target also makes
    Windows send the user's NTLM hash to that host."""
    t = target.strip().strip('"').lower()
    # `mhtml:http://...` (CVE-2021-40444) and similar wrappers of a URL.
    t = t.removeprefix("mhtml:").removeprefix("!x-usc:")
    if t.startswith(("http://", "https://", "\\\\", "//", "file:\\\\")):
        return True
    if not t.startswith("file://"):
        return False
    # `file://host/x` names a host; `file:///c:/x` is local, but
    # `file:////host/x` and `file:///\\\\host\\x` are UNC paths again.
    rest = t.removeprefix("file://")
    if rest.startswith(("//", "/\\\\")):
        return True
    return not rest.startswith("/")


_DDE = re.compile(r"\bDDE(?:AUTO)?\b", re.IGNORECASE)
_INCLUDE = re.compile(
    r"\b(?:INCLUDEPICTURE|INCLUDETEXT|LINK|IMPORT)\b(?:\s+\\\S+)*\s+(\"[^\"]*\"|\S+)",
    re.IGNORECASE,
)


def scan_field_codes(codes: str) -> dict[str, str]:
    """Findings in Word field instructions: DDE/DDEAUTO runs a command when
    the document opens (critical); INCLUDEPICTURE, INCLUDETEXT, LINK and
    IMPORT with a remote target load it (external reference)."""
    found: dict[str, str] = {}
    if _DDE.search(codes):
        found["office_dde"] = "critical"
    if any(is_remote(m.group(1)) for m in _INCLUDE.finditer(codes)):
        found["office_external_reference"] = "warn"
    return found


def field_codes(text: str) -> str:
    """The instruction parts of all fields in a .doc text, space-joined
    (0x13 code 0x14 result 0x15, fields may nest)."""
    codes: list[str] = []
    stack: list[tuple[list[str], list[bool]]] = []  # (code chars, [in code part])
    for ch in text:
        if ch == "\x13":
            stack.append(([], [True]))
        elif ch == "\x14" and stack:
            stack[-1][1][0] = False
        elif ch == "\x15" and stack:
            codes.append("".join(stack.pop()[0]))
        elif stack and stack[-1][1][0]:
            stack[-1][0].append(ch)
    return " ".join(codes)


def _u16(buf: bytes, off: int) -> int:
    return int(struct.unpack_from("<H", buf, off)[0])


def _u32(buf: bytes, off: int) -> int:
    return int(struct.unpack_from("<I", buf, off)[0])


def doc_text(ole: Any) -> str | dict[str, Any]:
    """Main-document text through the piece table ([MS-DOC] 2.4.1)."""
    wd = ole.openstream("WordDocument").read()
    flags = _u16(wd, 0x0A)
    if flags & 0x0100:
        return failure("office_encrypted", "the document is protected with a password")
    table_name = "1Table" if flags & 0x0200 else "0Table"
    if not ole.exists(table_name):
        return failure("invalid_office_document", "the document has no table stream")
    table = ole.openstream(table_name).read()
    ccp_text = _u32(wd, 34 + _u16(wd, 32) * 2 + 2 + 3 * 4)  # FibRgLw97.ccpText
    pos = _fc_lcb_base(wd)
    fc_clx, lcb_clx = _u32(wd, pos + 33 * 8), _u32(wd, pos + 33 * 8 + 4)
    clx = table[fc_clx : fc_clx + lcb_clx]
    i = 0
    while i < len(clx) and clx[i] == 0x01:  # Prc entries before the piece table
        i += 3 + _u16(clx, i + 1)
    if i >= len(clx) or clx[i] != 0x02:
        return failure("invalid_office_document", "the document has no piece table")
    plc = clx[i + 5 : i + 5 + _u32(clx, i + 1)]
    count = (len(plc) - 4) // 12
    cps = [_u32(plc, 4 * k) for k in range(count + 1)]
    pieces = []
    for k in range(count):
        fc = _u32(plc, 4 * (count + 1) + 8 * k + 2)
        length = cps[k + 1] - cps[k]
        if fc & 0x40000000:
            start = (fc & 0x3FFFFFFF) // 2
            pieces.append(wd[start : start + length].decode("cp1252", errors="replace"))
        else:
            pieces.append(wd[fc : fc + 2 * length].decode("utf-16-le", errors="replace"))
    return "".join(pieces)[:ccp_text]


def drop_field_codes(text: str) -> str:
    """Keep field results, drop field instructions (0x13 code 0x14 result 0x15)."""
    out: list[str] = []
    stack: list[bool] = []  # per open field: True while in its code part
    for ch in text:
        if ch == "\x13":
            stack.append(True)
        elif ch == "\x14" and stack:
            stack[-1] = False
        elif ch == "\x15" and stack:
            stack.pop()
        elif not any(stack):
            out.append(ch)
    return "".join(out)


_DOC_CHARS = str.maketrans(
    {"\x0b": "\n", "\x0c": "\n", "\x1e": "-", "\x1f": None, "\x02": None, "\x05": None}
)


def doc_markdown(text: str) -> tuple[str, int]:
    text = drop_field_codes(text)
    images = text.count("\x01") + text.count("\x08")
    text = re.sub("[\x01\x08]", f" {IMAGE_MARKER} ", text)
    text = re.sub(" {2,}", " ", text)
    text = text.translate(_DOC_CHARS)
    blocks: list[str] = []
    rows: list[list[str]] = []
    row: list[str] = []
    cell: list[str] = []
    buf: list[str] = []
    after_cell = False

    def flush_table() -> None:
        if rows:
            blocks.append(_table_markdown(rows))
            rows.clear()

    for ch in text:
        if ch == "\x07":
            if after_cell and not buf and not cell:
                # A second cell mark in a row: the row-end mark.
                rows.append(row)
                row = []
                after_cell = False
                continue
            cell.append("".join(buf).strip())
            row.append(" ".join(p for p in cell if p))
            buf, cell = [], []
            after_cell = True
        elif ch == "\r":
            if row or cell:
                cell.append("".join(buf).strip())
            else:
                flush_table()
                paragraph = "".join(buf).strip()
                if paragraph:
                    blocks.append("\n".join(escape_line(line) for line in paragraph.split("\n")))
            buf = []
            after_cell = False
        else:
            buf.append(ch)
            after_cell = False
    if row:
        rows.append(row)
    flush_table()
    tail = "".join(buf).strip()
    if tail:
        blocks.append(escape_line(tail))
    return "\n\n".join(blocks), images


def _table_markdown(rows: list[list[str]]) -> str:
    """Rows as a Markdown table through the same converter as .docx/.odt
    tables, so all three formats render tables alike."""
    width = max(len(row) for row in rows)
    body = "".join(
        "<tr>"
        + "".join(f"<td>{html.escape(cell)}</td>" for cell in row + [""] * (width - len(row)))
        + "</tr>"
        for row in rows
    )
    return html_to_markdown(f"<table>{body}</table>", infer_table_header=True)


def scan_doc(ole: Any) -> dict[str, str]:
    """Findings of a .doc: VBA storages, embedded objects and a remote
    attached template."""
    found: dict[str, str] = {}
    if ole.exists("ObjectPool"):
        found["office_embedded_object"] = "warn"
    if ole.exists("Macros") or ole.exists("_VBA_PROJECT_CUR"):
        found["office_macros"] = "critical"
    template = attached_template(ole)
    if template and is_remote(template):
        found["office_remote_template"] = "critical"
    return found


def attached_template(ole: Any) -> str | None:
    """The attached template path (SttbfAssoc entry ibstAssocDot, [MS-DOC]
    2.9.18), or None."""
    try:
        wd = ole.openstream("WordDocument").read()
        table = ole.openstream("1Table" if _u16(wd, 0x0A) & 0x0200 else "0Table").read()
        pos = _fc_lcb_base(wd)
        fc, lcb = _u32(wd, pos + 32 * 8), _u32(wd, pos + 32 * 8 + 4)
        strings = _sttb(table[fc : fc + lcb])
    except Exception:
        return None
    return strings[1] if len(strings) > 1 and strings[1] else None


def _fc_lcb_base(wd: bytes) -> int:
    """Offset of FibRgFcLcb97 in the FIB."""
    pos = 34 + _u16(wd, 32) * 2
    return pos + 2 + _u16(wd, pos) * 4 + 2


def _sttb(buf: bytes) -> list[str]:
    """Strings of an STTB: extended (UTF-16, 2-byte counts) or not."""
    if len(buf) < 6:
        return []
    extended = _u16(buf, 0) == 0xFFFF
    pos = 2 if extended else 0
    count, extra = _u16(buf, pos), _u16(buf, pos + 2)
    pos += 4
    out = []
    for _ in range(count):
        if extended:
            cch = _u16(buf, pos)
            out.append(buf[pos + 2 : pos + 2 + 2 * cch].decode("utf-16-le", errors="replace"))
            pos += 2 + 2 * cch
        else:
            cch = buf[pos]
            out.append(buf[pos + 1 : pos + 1 + cch].decode("cp1252", errors="replace"))
            pos += 1 + cch
        pos += extra
    return out
