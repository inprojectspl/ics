"""PDF extraction: the child process, its timeout, and the active-content scan.

`run_extraction` is what every write of a PDF goes through, so these tests
call it (a real `python -m app.pdf_extract` child) rather than the pure
function alone.
"""

from __future__ import annotations

import pytest

from app import child_process
from app.config import get_settings
from app.domain_errors import DomainError
from app.errors import domain_status
from app.pdf_extract import clean_text, extract_pdf, main, scan_active_content
from app.services import documents
from tests.pdf_factory import make_glyph_placed_pdf, make_pdf


def _rules(result: dict) -> dict[str, str]:
    return {f["rule"]: f["severity"] for f in result["findings"]}


@pytest.mark.asyncio
async def test_child_process_extracts_pages_and_bookmarks():
    data = make_pdf(
        ["First page about kangaroos", None, "Third page"],
        bookmarks=[("Intro", 0, 1), ("Details", 2, 2)],
    )
    result = await documents.run_extraction("pdf_doc", data, get_settings())
    assert result["page_count"] == 3
    assert result["pages"] == ["First page about kangaroos", "", "Third page"]
    assert result["bookmarks"] == [
        {"level": 1, "title": "Intro", "page": 1},
        {"level": 2, "title": "Details", "page": 3},
    ]
    assert result["findings"] == []
    assert result["truncated"] is False


@pytest.mark.asyncio
async def test_child_process_is_killed_after_the_timeout():
    settings = get_settings().model_copy(update={"pdf_extract_timeout_seconds": 0.001})
    with pytest.raises(DomainError) as exc:
        await documents.run_extraction("pdf_doc", make_pdf(["text"]), settings)
    assert exc.value.code == "pdf_extraction_failed"
    assert domain_status(exc.value) == 400


@pytest.mark.asyncio
async def test_child_process_crash_is_a_domain_error(monkeypatch):
    # A child that dies without writing JSON must not surface as a 500.
    monkeypatch.setattr(child_process.sys, "executable", "/usr/bin/false")
    with pytest.raises(DomainError) as exc:
        await documents.run_extraction("pdf_doc", make_pdf(["text"]), get_settings())
    assert exc.value.code == "pdf_extraction_failed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"PK\x03\x04 a zip file", "invalid_pdf"),
        (b"%PDF-1.7\n this is not a real document", "invalid_pdf"),
        (make_pdf(["secret"], user_password="pw", owner_password="owner"), "pdf_encrypted"),
    ],
    # Encrypted bytes differ per run; xdist needs stable ids on every worker.
    ids=["not-a-pdf", "broken-pdf", "password-protected"],
)
async def test_unreadable_pdfs_are_rejected_with_a_code(data, code):
    with pytest.raises(DomainError) as exc:
        await documents.run_extraction("pdf_doc", data, get_settings())
    assert exc.value.code == code
    assert domain_status(exc.value) == 400


def test_owner_password_only_pdf_opens():
    # Restrictions-only encryption (empty user password) is how many
    # generators ship PDFs; the text is readable without a password.
    result = extract_pdf(
        make_pdf(["open text"], owner_password="owner"), max_pages=5, max_chars=100
    )
    assert result["ok"] is True
    assert result["pages"] == ["open text"]


@pytest.mark.parametrize(
    ("kwargs", "rule", "severity"),
    [
        ({"javascript": True}, "pdf_javascript", "warn"),
        ({"launch": True}, "pdf_launch_action", "critical"),
        ({"embedded": True}, "pdf_embedded_file", "warn"),
        ({"xfa": True}, "pdf_xfa_form", "warn"),
    ],
)
def test_scanner_flags_active_content(kwargs, rule, severity):
    result = extract_pdf(make_pdf(["text"], **kwargs), max_pages=5, max_chars=1000)
    assert _rules(result) == {rule: severity}


def test_scanner_finds_content_inside_compressed_object_streams():
    # pypdf writes the document catalog and actions into object streams when
    # compressing; a byte grep for /JavaScript would miss them.
    import io

    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter(clone_from=io.BytesIO(make_pdf(["text"], javascript=True)))
    writer.compress_identical_objects()
    buf = io.BytesIO()
    writer.write(buf)
    reader = PdfReader(io.BytesIO(buf.getvalue()))
    assert {f["rule"] for f in scan_active_content(reader)} == {"pdf_javascript"}


def test_limits_mark_unextracted_pages_and_truncate():
    data = make_pdf(["a" * 50, "b" * 50, "c" * 50])
    by_pages = extract_pdf(data, max_pages=1, max_chars=10_000)
    assert by_pages["pages"] == ["a" * 50, None, None]
    assert by_pages["truncated"] is True

    by_chars = extract_pdf(data, max_pages=10, max_chars=70)
    assert by_chars["pages"] == ["a" * 50, "b" * 20, None]
    assert by_chars["truncated"] is True


_POLICY = (
    "the security policy applies to every information system of the state "
    "administration and its agencies"
)


@pytest.mark.asyncio
async def test_glyph_placed_text_gets_word_breaks_from_positions():
    data = make_glyph_placed_pdf(_POLICY)
    # Through the child process (pdfium under its memory limit) and in process.
    result = await documents.run_extraction("pdf_doc", data, get_settings())
    assert result["pages"] == [_POLICY]
    assert extract_pdf(data, max_pages=5, max_chars=10_000)["pages"] == [_POLICY]


def test_glyph_placed_text_keeps_parser_text_when_pdfium_fails(monkeypatch):
    import pypdfium2

    def broken(*_args, **_kwargs):
        raise pypdfium2.PdfiumError("damaged")

    monkeypatch.setattr(pypdfium2, "PdfDocument", broken)
    result = extract_pdf(make_glyph_placed_pdf(_POLICY), max_pages=5, max_chars=10_000)
    # Spaced out, but the text is still there to search.
    assert result["pages"][0].replace(" ", "") == _POLICY.replace(" ", "")


def test_clean_text_normalizes_whitespace_and_control_characters():
    assert clean_text("a\x00b  \r\n\r\n\r\n\nc\x0c ") == "ab\n\nc"


def test_main_reads_stdin_and_writes_json(monkeypatch, capsys):
    import io
    import json
    import sys

    monkeypatch.setattr(sys, "stdin", type("S", (), {"buffer": io.BytesIO(make_pdf(["hi"]))})())
    assert main(["10", "1000", str(4 * 1024**3)]) == 0
    assert json.loads(capsys.readouterr().out)["pages"] == ["hi"]


def test_bookmarks_in_process_nested_and_broken_outline():
    data = make_pdf(["a", "b"], bookmarks=[("Top", 0, 1), ("Child", 1, 2)])
    result = extract_pdf(data, max_pages=5, max_chars=100)
    assert result["bookmarks"] == [
        {"level": 1, "title": "Top", "page": 1},
        {"level": 2, "title": "Child", "page": 2},
    ]

    import io

    from pypdf import PdfReader

    from app import pdf_extract

    class BrokenOutline:
        outline = property(lambda self: (_ for _ in ()).throw(ValueError("bad outline")))

    assert pdf_extract._bookmarks(BrokenOutline()) == []
    reader = PdfReader(io.BytesIO(data))
    assert [b["title"] for b in pdf_extract._bookmarks(reader)] == ["Top", "Child"]
