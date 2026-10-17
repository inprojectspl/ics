"""Word/ODF conversion: the child process, its limits and the scan.

`run_extraction("office_doc", ...)` is what every write of a document goes
through, so the integration-level cases run a real child process.
"""

from __future__ import annotations

import pytest

from app import child_process
from app.config import get_settings
from app.domain_errors import DomainError
from app.errors import domain_status
from app.office_extract import detect_format, extract_office, main
from app.services import documents
from tests.office_factory import doc_text, make_doc, make_docx, make_odt, make_ole, zip_bomb

LIMITS = {"max_chars": 1_000_000, "max_unzipped": 50_000_000}


def _rules(data: bytes) -> dict[str, str]:
    result = extract_office(data, **LIMITS)
    assert result["ok"], result
    return {f["rule"]: f["severity"] for f in result["findings"]}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("data", "fmt"),
    [
        (make_docx([("p", "docx body")]), "docx"),
        (make_odt([("p", "odt body")]), "odt"),
        (make_doc(doc_text(["doc body"])), "doc"),
    ],
    ids=["docx", "odt", "doc"],
)
async def test_child_process_converts_each_format(data, fmt):
    result = await documents.run_extraction("office_doc", data, get_settings())
    assert result["format"] == fmt
    assert f"{fmt} body" in result["markdown"]
    assert result["findings"] == []


@pytest.mark.asyncio
async def test_child_process_is_killed_after_the_timeout():
    settings = get_settings().model_copy(update={"office_convert_timeout_seconds": 0.001})
    with pytest.raises(DomainError) as exc:
        await documents.run_extraction("office_doc", make_docx([("p", "x")]), settings)
    assert exc.value.code == "office_conversion_failed"
    assert domain_status(exc.value) == 400


@pytest.mark.asyncio
async def test_child_process_crash_is_a_domain_error(monkeypatch):
    monkeypatch.setattr(child_process.sys, "executable", "/usr/bin/false")
    with pytest.raises(DomainError) as exc:
        await documents.run_extraction("office_doc", make_docx([("p", "x")]), get_settings())
    assert exc.value.code == "office_conversion_failed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"just some text renamed to .docx", "invalid_office_document"),
        (b"PK\x03\x04 a broken zip", "invalid_office_document"),
        (make_ole({"Workbook": b"xls"}), "invalid_office_document"),
        (make_ole({"EncryptionInfo": b"x", "EncryptedPackage": b"y"}), "office_encrypted"),
        (make_doc(doc_text(["secret"]), encrypted=True), "office_encrypted"),
        (make_odt([("p", "secret")], encrypted=True), "office_encrypted"),
    ],
    ids=["text", "broken-zip", "other-ole", "encrypted-docx", "encrypted-doc", "encrypted-odt"],
)
async def test_unreadable_documents_are_rejected_with_a_code(data, code):
    with pytest.raises(DomainError) as exc:
        await documents.run_extraction("office_doc", data, get_settings())
    assert exc.value.code == code
    assert domain_status(exc.value) == 400


def test_zip_bomb_is_refused_before_unpacking():
    result = extract_office(zip_bomb(20_000_000), max_chars=100, max_unzipped=10_000_000)
    assert result == {
        "ok": False,
        "code": "office_too_large",
        "detail": "the document unpacks to too much data",
    }


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (make_docx([("p", "x")], macros=True), {"office_macros": "critical"}),
        (make_odt([("p", "x")], macros=True), {"office_macros": "critical"}),
        (make_doc(doc_text(["x"]), macros=True), {"office_macros": "critical"}),
        (
            make_docx([("p", "x")], remote_template="https://evil.example/t.dotm"),
            {"office_remote_template": "critical"},
        ),
        (
            make_docx([("p", "x")], local_template="file:///C:/Templates/Normal.dotm"),
            {"office_external_reference": "warn"},
        ),
        (make_docx([("p", "x")], embedded=True), {"office_embedded_object": "warn"}),
        (make_odt([("p", "x")], embedded=True), {"office_embedded_object": "warn"}),
    ],
    ids=[
        "docx-macros",
        "odt-macros",
        "doc-macros",
        "remote-template",
        "local-template",
        "docx-embedded",
        "odt-embedded",
    ],
)
def test_scanner_flags_active_content(data, expected):
    assert _rules(data) == expected


def test_hyperlinks_are_not_findings():
    assert _rules(make_odt([("p", "x")], link=("site", "https://example.com"))) == {}


def test_format_comes_from_content_not_name():
    assert detect_format(make_docx([("p", "x")])) == "docx"
    assert detect_format(make_odt([("p", "x")])) == "odt"
    assert detect_format(make_doc(doc_text(["x"]))) == "doc"
    assert detect_format(b"%PDF-1.7") is None


def test_docx_title_and_subtitle_become_headings():
    data = make_docx([("title", "Annual report"), ("subtitle", "Draft"), ("h1", "Scope")])
    lines = extract_office(data, **LIMITS)["markdown"].splitlines()
    assert "# Annual report" in lines
    assert "## Draft" in lines
    assert "# Scope" in lines


def test_text_over_the_limit_is_truncated():
    result = extract_office(make_docx([("p", "a" * 500)]), max_chars=100, max_unzipped=10**8)
    assert result["truncated"] is True
    assert len(result["markdown"]) == 100


def test_main_reads_stdin_and_writes_json(monkeypatch, capsys):
    import io
    import json
    import sys

    data = make_docx([("p", "from stdin")])
    monkeypatch.setattr(sys, "stdin", type("S", (), {"buffer": io.BytesIO(data)})())
    assert main(["1000", "100000000", str(4 * 1024**3)]) == 0
    assert "from stdin" in json.loads(capsys.readouterr().out)["markdown"]
