"""Word (docx, doc) and ODF text as Markdown, plus a scan for active content.

Runs as a killable child process (`python -m app.office_extract`, bytes on stdin,
JSON on stdout) like `pdf_extract`, so imports from `app` stay pure. The format is
sniffed from content; images are never read, only counted as `[image]` markers.
"""

from __future__ import annotations

import html
import io
import json
import re
import sys
import zipfile
from typing import Any, ClassVar

from app.html_markdown import html_to_markdown
from app.pdf_extract import failure, limit_resources
from app.word97 import (
    IMAGE_MARKER,
    doc_markdown,
    doc_text,
    field_codes,
    is_remote,
    scan_doc,
    scan_field_codes,
)

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
ZIP_MAGIC = b"PK\x03\x04"
ODT_MIMETYPES = (
    b"application/vnd.oasis.opendocument.text",
    b"application/vnd.oasis.opendocument.text-template",
)
_MAX_ZIP_ENTRIES = 5_000
_BLANK_RUN = re.compile(r"\n{3,}")
# Relationship types that make Word fetch and run something external when
# the document opens (remote template injection and its relatives).
_FETCHING_RELS = ("attachedTemplate", "oleObject", "frame", "subDocument")
# Internal relationships to parts an editor opens or runs as an object.
# altChunk (`aFChunk`) imports another document (RTF, HTML, MHT) that may
# itself carry OLE objects.
_EMBEDDED_RELS = ("oleObject", "package", "control", "activeXControlBinary", "aFChunk")


def _finding(found: dict[str, str], rule: str, severity: str) -> None:
    if found.get(rule) != "critical":
        found[rule] = severity


# Detection


def detect_format(data: bytes) -> str | None:
    """`docx`, `odt`, `doc`, `encrypted` or None for anything else."""
    if data.startswith(OLE_MAGIC):
        try:
            import olefile

            # The stubs type stream names as bytes; olefile takes str too.
            ole: Any = olefile.OleFileIO(data)
        except Exception:
            return None
        if ole.exists("WordDocument"):
            return "doc"
        # A password-protected .docx/.odt is an OLE wrapper around the
        # encrypted package.
        if ole.exists("EncryptionInfo") or ole.exists("EncryptedPackage"):
            return "encrypted"
        return None
    if not data.startswith(ZIP_MAGIC):
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
            if "word/document.xml" in names:
                return "docx"
            if "mimetype" in names and zf.read("mimetype").strip() in ODT_MIMETYPES:
                return "odt"
    except zipfile.BadZipFile:
        return None
    return None


def _check_zip(data: bytes, max_unzipped: int) -> zipfile.ZipFile | dict[str, Any]:
    """Open the archive only if its declared size is sane (zip bomb guard)."""
    zf = zipfile.ZipFile(io.BytesIO(data))
    infos = zf.infolist()
    if len(infos) > _MAX_ZIP_ENTRIES or sum(i.file_size for i in infos) > max_unzipped:
        return failure("office_too_large", "the document unpacks to too much data")
    return zf


def _safe_xml(raw: bytes) -> Any:
    from lxml import etree

    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False
    )
    return etree.fromstring(raw, parser=parser)


# DOCX


_IMG_TAG = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_FOOTNOTE_REF = re.compile(r"\[\[(\d+)\]\]\(#footnote-\d+\)")
_FOOTNOTE_BACKREF = re.compile(r" ?\[↑\]\(#footnote-ref-\d+\)")


# mammoth maps Heading 1-6 but leaves Title and Subtitle as plain paragraphs.
# Matched by name too, because localized Word writes its own style ids.
_DOCX_STYLE_MAP = """
p.Title => h1:fresh
p[style-name='Title'] => h1:fresh
p.Subtitle => h2:fresh
p[style-name='Subtitle'] => h2:fresh
"""


def _docx_markdown(data: bytes) -> tuple[str, int]:
    import mammoth
    import mammoth.images

    images = 0

    def no_image(image: Any) -> dict[str, str]:
        # Never open the image: mammoth would read (and base64) its bytes.
        nonlocal images
        images += 1
        return {"src": "", "alt": image.alt_text or ""}

    result = mammoth.convert_to_html(
        io.BytesIO(data),
        convert_image=mammoth.images.img_element(no_image),
        style_map=_DOCX_STYLE_MAP,
    )
    body = _IMG_TAG.sub(f"<em>{IMAGE_MARKER}</em>", result.value)
    markdown = html_to_markdown(body, infer_table_header=True)
    # mammoth links footnotes both ways; in Markdown the anchors are noise.
    markdown = _FOOTNOTE_BACKREF.sub("", _FOOTNOTE_REF.sub(r"[\1]", markdown))
    return markdown, images


def _scan_docx(zf: zipfile.ZipFile, found: dict[str, str]) -> None:
    for name in zf.namelist():
        low = name.lower()
        if low.endswith("vbaproject.bin"):
            _finding(found, "office_macros", "critical")
        elif low.startswith(("word/embeddings/", "word/activex/")):
            _finding(found, "office_embedded_object", "warn")
        elif low.endswith(".rels"):
            _scan_rels(zf.read(name), found)
        elif low.endswith(".xml"):
            # Any part: the main document may be moved out of `word/`.
            _scan_fields(zf.read(name), found)
    # Macros and objects can sit under any part name: the package declares
    # them through content types (and relationships, see `_scan_rels`).
    try:
        types = zf.read("[Content_Types].xml").lower()
    except KeyError:
        return
    if b"vbaproject" in types or b"macroenabled" in types:
        _finding(found, "office_macros", "critical")
    if b"oleobject" in types or b"activex" in types:
        _finding(found, "office_embedded_object", "warn")


def _scan_fields(raw: bytes, found: dict[str, str]) -> None:
    """Field instructions of one WordprocessingML part (`w:instrText` runs
    and `w:fldSimple`): DDE and remote INCLUDE* fields."""
    if b"instr" not in raw and b"Macro" not in raw:
        return
    try:
        root = _safe_xml(raw)
    except Exception:
        return
    fields: list[str] = []
    current: list[str] = []
    form_macro = False
    # Matched by local name: Strict OOXML uses another namespace URI.
    # Word concatenates the instrText runs of one field without separators,
    # so `DD` + `EAUTO` split across runs is still DDEAUTO.
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        local = el.tag.rsplit("}", 1)[-1]
        if local == "instrText":
            current.append(el.text or "")
        elif local == "fldChar" and _attr(el, "fldCharType") in ("begin", "separate", "end"):
            fields.append("".join(current))
            current = []
        elif local == "fldSimple":
            fields.append(_attr(el, "instr"))
        elif local in ("entryMacro", "exitMacro"):
            # Legacy form fields name a macro that runs on entry or exit.
            form_macro = True
    fields.append("".join(current))
    for rule, severity in scan_field_codes(" ".join(fields)).items():
        _finding(found, rule, severity)
    if form_macro:
        _finding(found, "office_macros", "critical")


def _attr(el: Any, local: str) -> str:
    """An attribute by local name, whatever its namespace."""
    for key, value in el.attrib.items():
        if key.rsplit("}", 1)[-1] == local:
            return str(value)
    return ""


def _scan_rels(raw: bytes, found: dict[str, str]) -> None:
    try:
        root = _safe_xml(raw)
    except Exception:
        return
    for rel in root:
        kind = (rel.get("Type") or "").rsplit("/", 1)[-1]
        if kind.lower() == "vbaproject":
            _finding(found, "office_macros", "critical")
        if rel.get("TargetMode") != "External":
            if kind in _EMBEDDED_RELS:
                _finding(found, "office_embedded_object", "warn")
            continue
        if kind == "hyperlink":
            # Followed only when the reader clicks it.
            continue
        if kind in _FETCHING_RELS and is_remote(rel.get("Target") or ""):
            _finding(found, "office_remote_template", "critical")
        else:
            # Linked images and other external parts: loaded on open.
            _finding(found, "office_external_reference", "warn")


# ODT


_NS = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "draw": "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0",
    "xlink": "http://www.w3.org/1999/xlink",
}


def _q(prefix: str, local: str) -> str:
    return f"{{{_NS[prefix]}}}{local}"


class _OdtWriter:
    """content.xml of an ODF text document to HTML, for `html_to_markdown`."""

    _SKIP: ClassVar[frozenset[str]] = frozenset(
        {
            _q("text", "tracked-changes"),
            _q("office", "annotation"),
            _q("office", "annotation-end"),
            _q("text", "sequence-decls"),
            _q("text", "variable-decls"),
            _q("text", "table-of-content-source"),
        }
    )

    def __init__(self) -> None:
        self.images = 0
        self.notes: list[str] = []

    def block(self, el: Any) -> str:
        tag = el.tag
        # Comments and processing instructions have a non-string tag.
        if not isinstance(tag, str) or tag in self._SKIP:
            return ""
        if tag == _q("text", "h"):
            level = min(max(int(el.get(_q("text", "outline-level")) or 1), 1), 6)
            return f"<h{level}>{self.inline(el)}</h{level}>"
        if tag == _q("text", "p"):
            return f"<p>{self.inline(el)}</p>"
        if tag == _q("text", "list"):
            items = "".join(
                f"<li>{self.blocks(item)}</li>"
                for item in el
                if item.tag == _q("text", "list-item")
            )
            return f"<ul>{items}</ul>"
        if tag == _q("table", "table"):
            return f"<table>{''.join(self.rows(el))}</table>"
        # Sections, index bodies and other containers: their children.
        return self.blocks(el)

    def blocks(self, el: Any) -> str:
        return "".join(self.block(child) for child in el)

    def rows(self, el: Any) -> list[str]:
        out = []
        for child in el:
            if child.tag == _q("table", "table-row"):
                cells = "".join(
                    f"<td>{self.blocks(cell)}</td>"
                    for cell in child
                    if cell.tag == _q("table", "table-cell")
                )
                out.append(f"<tr>{cells}</tr>")
            elif child.tag in (_q("table", "table-header-rows"), _q("table", "table-rows")):
                out.extend(self.rows(child))
        return out

    def inline(self, el: Any) -> str:
        parts = [html.escape(el.text or "")]
        for child in el:
            parts.append(self.inline_child(child))
            parts.append(html.escape(child.tail or ""))
        return "".join(parts)

    def inline_child(self, el: Any) -> str:
        tag = el.tag
        if not isinstance(tag, str) or tag in self._SKIP:
            return ""
        if tag == _q("text", "s"):
            return " " * int(el.get(_q("text", "c")) or 1)
        if tag == _q("text", "tab"):
            return " "
        if tag == _q("text", "line-break"):
            return "<br>"
        if tag == _q("text", "a"):
            href = html.escape(el.get(_q("xlink", "href")) or "", quote=True)
            return f'<a href="{href}">{self.inline(el)}</a>'
        if tag == _q("text", "note"):
            body = el.find(_q("text", "note-body"))
            self.notes.append(self.blocks(body) if body is not None else "")
            return f"<sup>[{len(self.notes)}]</sup>"
        if tag == _q("draw", "frame"):
            if el.find(_q("draw", "image")) is not None:
                self.images += 1
                return f"<em>{IMAGE_MARKER}</em>"
            # Text boxes hold paragraphs of their own.
            return " ".join(self.blocks(box) for box in el)
        return self.inline(el)

    def document(self, root: Any) -> str:
        body = root.find(f"{_q('office', 'body')}/{_q('office', 'text')}")
        out = self.blocks(body) if body is not None else ""
        if self.notes:
            items = "".join(f"<li>{note}</li>" for note in self.notes)
            out += f"<h2>Notes</h2><ol>{items}</ol>"
        return out


def _odt_markdown(zf: zipfile.ZipFile) -> tuple[str, int]:
    writer = _OdtWriter()
    body = writer.document(_safe_xml(zf.read("content.xml")))
    return html_to_markdown(body, infer_table_header=True), writer.images


def _scan_odt(zf: zipfile.ZipFile, found: dict[str, str]) -> bool:
    """Record findings; True when the document is encrypted."""
    for name in zf.namelist():
        if name.startswith(("Basic/", "Scripts/")):
            _finding(found, "office_macros", "critical")
        elif name.startswith(("Object ", "ObjectReplacements/")):
            _finding(found, "office_embedded_object", "warn")
    for part in ("content.xml", "styles.xml"):
        try:
            _scan_odt_links(_safe_xml(zf.read(part)), found)
        except KeyError:
            continue
        except Exception:
            # A broken part fails the conversion itself; nothing to add here.
            continue
    try:
        manifest = zf.read("META-INF/manifest.xml")
    except KeyError:
        return False
    return b"encryption-data" in manifest


_SCRIPT_NS = "{urn:oasis:names:tc:opendocument:xmlns:script:1.0}"

# Elements whose `xlink:href` LibreOffice loads when the document opens
# (a linked image, OLE object, section or plugin), unlike `text:a`.
_ODT_LOADED = {"image", "object", "object-ole", "section-source", "plugin", "applet"}


def _scan_odt_links(root: Any, found: dict[str, str]) -> None:
    href = _q("xlink", "href")
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        local = el.tag.rsplit("}", 1)[-1]
        target = (el.get(href) or "").strip().lower()
        if (
            el.tag.startswith(_SCRIPT_NS)
            or local == "execute-macro"
            or target.startswith(("vnd.sun.star.script:", "macro:"))
        ):
            # A script bound to an event (document load, mouse over), a
            # macro field or a script URL: runs code without the Basic/
            # library parts, e.g. through LibreLogo (CVE-2019-9848).
            _finding(found, "office_macros", "critical")
        elif local in ("dde-connection-decl", "dde-source"):
            # A DDE link runs a command in another application on update.
            _finding(found, "office_dde", "critical")
        elif local in ("object", "object-ole") and el.tag.startswith(f"{{{_NS['draw']}}}"):
            # An embedded object, whatever its part is called.
            _finding(found, "office_embedded_object", "warn")
            if is_remote(el.get(href) or ""):
                _finding(found, "office_external_reference", "warn")
        elif local in _ODT_LOADED and is_remote(el.get(href) or ""):
            _finding(found, "office_external_reference", "warn")


# Entry point


def extract_office(data: bytes, *, max_chars: int, max_unzipped: int) -> dict[str, Any]:
    fmt = detect_format(data)
    if fmt == "encrypted":
        return failure("office_encrypted", "the document is protected with a password")
    if fmt is None:
        return failure("invalid_office_document", "the file is not a Word or ODF text document")
    found: dict[str, str] = {}
    try:
        if fmt == "doc":
            import olefile

            ole = olefile.OleFileIO(data)
            text = doc_text(ole)
            if isinstance(text, dict):
                return text
            found.update(scan_doc(ole))
            for rule, severity in scan_field_codes(field_codes(text)).items():
                _finding(found, rule, severity)
            markdown, images = doc_markdown(text)
        else:
            zf = _check_zip(data, max_unzipped)
            if isinstance(zf, dict):
                return zf
            if fmt == "docx":
                _scan_docx(zf, found)
                markdown, images = _docx_markdown(data)
            else:
                if _scan_odt(zf, found):
                    return failure("office_encrypted", "the document is protected with a password")
                markdown, images = _odt_markdown(zf)
    except Exception as exc:
        return failure(
            "invalid_office_document", f"the document cannot be read: {type(exc).__name__}"
        )
    markdown = _BLANK_RUN.sub("\n\n", markdown).strip()
    truncated = len(markdown) > max_chars
    return {
        "ok": True,
        "format": fmt,
        "markdown": markdown[:max_chars],
        "images": images,
        "findings": [{"rule": r, "severity": s} for r, s in sorted(found.items())],
        "truncated": truncated,
    }


def main(argv: list[str]) -> int:
    max_chars, max_unzipped, memory_bytes = (int(a) for a in argv)
    limit_resources(memory_bytes)
    data = sys.stdin.buffer.read()
    try:
        result = extract_office(data, max_chars=max_chars, max_unzipped=max_unzipped)
    except MemoryError:
        result = failure("office_conversion_failed", "the document needs too much memory")
    sys.stdout.write(json.dumps(result))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the subprocess
    raise SystemExit(main(sys.argv[1:]))
