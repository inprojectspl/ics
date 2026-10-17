"""Converter details, in process: the ODF walker, the Word 97 text reader
and the relationship scan. The child-process path is in
test_office_extract.py; these cases pin the markup mapping."""

from __future__ import annotations

from app.office_extract import IMAGE_MARKER, _scan_rels, extract_office
from app.word97 import doc_markdown as _doc_markdown
from app.word97 import drop_field_codes as _drop_field_codes
from tests.office_factory import _ODF_NS, _zip, doc_text, make_doc

LIMITS = {"max_chars": 1_000_000, "max_unzipped": 50_000_000}


def _odt(body: str) -> str:
    content = (
        f'<?xml version="1.0" encoding="UTF-8"?><office:document-content {_ODF_NS}>'
        f"<office:body><office:text>{body}</office:text></office:body></office:document-content>"
    )
    data = _zip({"mimetype": "application/vnd.oasis.opendocument.text", "content.xml": content})
    result = extract_office(data, **LIMITS)
    assert result["ok"], result
    return result["markdown"]


def test_odt_inline_markup():
    md = _odt(
        "<text:p>a<text:s text:c='3'/>b<text:tab/>c<text:line-break/>d"
        "<text:span>span</text:span><!-- hidden comment --></text:p>"
    )
    # HTML collapses runs of spaces; the line break stays a hard break.
    assert md.splitlines() == ["a b c  ", "dspan"]
    assert "hidden comment" not in md


def test_odt_sections_header_rows_text_boxes_and_skipped_parts():
    md = _odt(
        "<text:section><text:h text:outline-level='9'>Deep heading</text:h></text:section>"
        "<table:table><table:table-header-rows><table:table-row>"
        "<table:table-cell><text:p>H1</text:p></table:table-cell>"
        "<table:table-cell><text:p>H2</text:p></table:table-cell>"
        "</table:table-row></table:table-header-rows><table:table-row>"
        "<table:table-cell><text:p>v1</text:p></table:table-cell>"
        "<table:table-cell><text:p>v2</text:p></table:table-cell></table:table-row></table:table>"
        "<text:p><draw:frame><draw:text-box><text:p>boxed text</text:p></draw:text-box></draw:frame></text:p>"
        "<text:tracked-changes><text:p>deleted text</text:p></text:tracked-changes>"
        "<text:p>kept<office:annotation><text:p>a comment</text:p></office:annotation></text:p>"
    )
    lines = md.splitlines()
    assert "###### Deep heading" in lines
    assert "| H1 | H2 |" in lines
    assert "| v1 | v2 |" in lines
    assert "boxed text" in md
    assert "deleted text" not in md
    assert "a comment" not in md


def test_odt_links_notes_and_images():
    md = _odt(
        "<text:p>See <text:a xlink:href='https://example.com/a?b=1&amp;c=2'>docs</text:a>"
        "<text:note><text:note-body><text:p>First note</text:p></text:note-body></text:note>"
        "<text:note/></text:p>"
        "<text:p><draw:frame><draw:image xlink:href='Pictures/x.png'/></draw:frame></text:p>"
    )
    assert "[docs](https://example.com/a?b=1&c=2)" in md
    assert "See [docs](https://example.com/a?b=1&c=2)[1][2]" in md
    assert "## Notes" in md
    assert "1. First note" in md
    assert f"*{IMAGE_MARKER}*" in md


def test_odt_without_a_text_body_is_empty():
    content = f"<office:document-content {_ODF_NS}/>"
    data = _zip({"mimetype": "application/vnd.oasis.opendocument.text", "content.xml": content})
    assert extract_office(data, **LIMITS)["markdown"] == ""


def test_field_codes_are_dropped_and_results_kept():
    assert _drop_field_codes("a\x13 PAGE \x14 7\x15b") == "a 7b"
    assert _drop_field_codes("x\x13 TOC \x13 nested \x14in\x15 \x14out\x15y") == "xouty"
    assert _drop_field_codes("no result\x13 SEQ \x15 end") == "no result end"


def test_doc_text_edge_cases():
    md, images = _doc_markdown("line one\x0bline two\rtail \x08 without a mark")
    assert md.splitlines() == ["line one", "line two", "", f"tail {IMAGE_MARKER} without a mark"]
    assert images == 1
    # A table that ends the document without a row-end mark, uneven rows.
    md, _ = _doc_markdown("Head\r" + "a\x07b\x07\x07" + "c\x07")
    assert md.splitlines()[-3:] == ["| a | b |", "| --- | --- |", "| c |  |"]
    # Paragraphs inside a cell after the first one are joined; pipes are
    # escaped. (Without paragraph properties a paragraph in the very first
    # cell cannot be told from one before the table.)
    md, _ = _doc_markdown("z\x07p1\rp|2\x07\x07")
    assert "| z | p1 p\\|2 |" in md


def test_utf16_doc_text_round_trips():
    text = doc_text(["Crème brûlée, naïve façade"])
    assert (
        "Crème brûlée, naïve façade"
        in extract_office(make_doc(text, compressed=False), **LIMITS)["markdown"]
    )


def test_relationship_scan_ignores_hyperlinks_and_bad_xml():
    found: dict[str, str] = {}
    _scan_rels(b"<not xml", found)
    _scan_rels(
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        b'<Relationship Id="a" Type="x/hyperlink" Target="https://example.com" TargetMode="External"/>'
        b'<Relationship Id="b" Type="x/styles" Target="styles.xml"/>'
        b"</Relationships>",
        found,
    )
    assert found == {}
    _scan_rels(
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        b'<Relationship Id="c" Type="x/oleObject" Target="\\\\host\\share\\o.bin" TargetMode="External"/>'
        b"</Relationships>",
        found,
    )
    assert found == {"office_remote_template": "critical"}
