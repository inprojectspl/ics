"""OCR engine side (ADR-0021): the page layout of recognized boxes, the
render scale, the Markdown notes, the PDF overlay and the local provider's
child-process protocol (with a fake child and once with the real engine)."""

from __future__ import annotations

import io

import pytest

from app.config import get_settings
from app.ocr_local import layout_text, render_scale
from app.pdf_markdown import NO_TEXT_NOTE, OCR_BLANK_NOTE, OCR_NOTE, pages_markdown
from app.services import documents
from app.services.documents import RecognizedPages
from app.services.ocr.providers import LocalProvider, OcrFailure, get_provider
from tests.pdf_factory import make_pdf


def _box(left: float, top: float, right: float, bottom: float) -> list[list[float]]:
    return [[left, top], [right, top], [right, bottom], [left, bottom]]


def test_layout_joins_boxes_of_one_line_left_to_right():
    text = layout_text(
        [
            (_box(300, 102, 500, 128), "value"),
            (_box(10, 100, 200, 130), "Label:"),
            (_box(10, 140, 400, 170), "next line"),
        ]
    )
    assert text == "Label: value\nnext line"


def test_layout_separates_paragraphs_on_a_large_gap_and_drops_empty_boxes():
    text = layout_text(
        [
            (_box(10, 100, 200, 130), "first"),
            (_box(10, 135, 200, 165), "   "),
            (_box(10, 300, 200, 330), "second"),
        ]
    )
    assert text == "first\n\nsecond"
    assert layout_text([]) == ""


def test_render_scale_keeps_dpi_until_the_pixel_cap():
    assert render_scale(612, 792, dpi=200, max_pixels=40_000_000) == pytest.approx(200 / 72)
    # A0 at 200 dpi would be ~50 MP: scaled down to the cap.
    scale = render_scale(2384, 3370, dpi=200, max_pixels=10_000_000)
    assert 2384 * 3370 * scale * scale == pytest.approx(10_000_000)


def test_markdown_marks_ocr_pages_and_keeps_the_no_text_note_elsewhere():
    md = pages_markdown(["layer text", "ocr text", "", ""], ocr_pages={2, 3})
    sections = md.split("## Page ")[1:]
    assert OCR_NOTE not in sections[0]
    assert sections[1].startswith(f"2\n\n{OCR_NOTE}\n\nocr text")
    assert OCR_BLANK_NOTE in sections[2]
    assert NO_TEXT_NOTE in sections[3]


def test_overlay_fills_only_pages_without_a_text_layer():
    pdf = documents.document_type("pdf_doc")
    assert pdf.ocr is not None
    extraction = {"pages": ["real", "", "", None], "page_count": 4, "bookmarks": []}
    merged = pdf.ocr.overlay(
        extraction, RecognizedPages({1: "stale", 2: "scan text", 3: "", 9: "x"})
    )
    assert merged["pages"] == ["real", "scan text", "", None]
    assert merged["ocr_pages"] == [2, 3]
    meta = pdf.meta(merged)
    assert (meta["text_page_count"], meta["ocr_page_count"], meta["untexted_page_count"]) == (
        1,
        1,
        2,
    )


def test_only_pdf_supports_ocr_and_old_metas_count_missing_text():
    assert documents.supports_ocr("pdf_doc")
    for kind in ("office_doc", "md_single", "md_collection", "html_bundle"):
        assert not documents.supports_ocr(kind)
    assert documents.pages_without_text("pdf_doc", {"page_count": 5, "text_page_count": 2}) == 3


def test_unknown_provider_fails_with_a_code():
    with pytest.raises(OcrFailure) as exc:
        get_provider("nope")
    assert exc.value.code == "ocr_provider_unavailable"


class _Fake(LocalProvider):
    module = "tests.fake_ocr_child"
    chunk_pages = 2


async def _recognize(monkeypatch, mode: str, pages=(1, 2, 3)) -> dict[int, str]:
    monkeypatch.setenv("FAKE_OCR_MODE", mode)
    got: dict[int, str] = {}

    async def on_page(number: int, text: str) -> None:
        got[number] = text

    engine = await _Fake().recognize(b"%PDF-1.4", list(pages), get_settings(), on_page)
    assert engine == "fake 1.0"
    return got


@pytest.mark.asyncio
async def test_provider_reports_every_page_across_chunks(monkeypatch):
    got = await _recognize(monkeypatch, "ok")
    assert got == {1: "text of page 1", 2: "text of page 2", 3: "text of page 3"}


@pytest.mark.asyncio
async def test_provider_caps_the_child_threads_and_malloc_arenas(monkeypatch):
    # Without it a many-core host blows the child's address-space limit.
    monkeypatch.setattr(get_settings(), "ocr_threads", 3)
    got = await _recognize(monkeypatch, "env", pages=(1,))
    assert got == {1: "2/3"}


@pytest.mark.parametrize(
    ("mode", "code"),
    [
        ("error", "ocr_out_of_memory"),
        ("crash", "ocr_engine_failed"),
        ("skip", "ocr_engine_failed"),
        ("no_done", "ocr_engine_failed"),
    ],
)
@pytest.mark.asyncio
async def test_provider_turns_child_failures_into_codes(monkeypatch, mode, code):
    with pytest.raises(OcrFailure) as exc:
        await _recognize(monkeypatch, mode)
    assert exc.value.code == code


@pytest.mark.asyncio
async def test_provider_kills_a_child_stuck_on_a_page(monkeypatch):
    monkeypatch.setattr(get_settings(), "ocr_page_timeout_seconds", 1)
    with pytest.raises(OcrFailure) as exc:
        await _recognize(monkeypatch, "hang", pages=(1,))
    assert exc.value.code == "ocr_page_timeout"


def _scanned_pdf(text: str) -> bytes:
    """One page that is only an image of `text`, like a scanner's output."""
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (1654, 600), "white")
    draw = ImageDraw.Draw(image)
    draw.text((100, 200), text, fill="black", font=ImageFont.load_default(size=64))
    buf = io.BytesIO()
    image.save(buf, format="PDF", resolution=200)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_real_engine_reads_a_scanned_page():
    got: dict[int, str] = {}

    async def on_page(number: int, text: str) -> None:
        got[number] = text

    engine = await LocalProvider().recognize(
        _scanned_pdf("Invoice 2026 total 125"), [1, 2], get_settings(), on_page
    )
    assert engine.startswith("rapidocr")
    assert "Invoice" in got[1] and "2026" in got[1]
    # A page number past the end reads as empty, it does not fail the run.
    assert got[2] == ""


def test_extraction_flags_an_invisible_layer_over_a_scan_only():
    from app.pdf_extract import extract_pdf

    data = make_pdf(["visible text", "saved by the scanner", None], scanned_text=[1])
    result = extract_pdf(data, max_pages=10, max_chars=10_000)
    assert result["pages"][1] == "saved by the scanner"
    assert result["hidden_text_pages"] == [2]


def test_overlay_replaces_a_saved_layer_but_never_visible_text():
    pdf = documents.document_type("pdf_doc")
    assert pdf.ocr is not None
    extraction = {
        "pages": ["visible", "notionole o déllbéré", ""],
        "hidden_text_pages": [2],
        "page_count": 3,
        "bookmarks": [],
    }
    before = pdf.meta(extraction)
    assert (before["hidden_text_page_count"], before["untexted_page_count"]) == (1, 1)
    merged = pdf.ocr.overlay(
        extraction, RecognizedPages({1: "x", 2: "nationale a délibéré", 3: "scan"})
    )
    assert merged["pages"] == ["visible", "nationale a délibéré", "scan"]
    meta = pdf.meta(merged)
    assert meta["text_page_count"] == 1
    assert meta["ocr_page_count"] == 2
    assert (meta["hidden_text_page_count"], meta["untexted_page_count"]) == (0, 1)


@pytest.mark.asyncio
async def test_split_child_cuts_the_requested_pages():
    from pypdf import PdfReader

    from app.services.ocr.mistral import _split

    part = await _split(make_pdf(["one", "two", "three"]), [3, 1], get_settings())
    texts = [p.extract_text().strip() for p in PdfReader(io.BytesIO(part)).pages]
    assert texts == ["three", "one"]
    with pytest.raises(OcrFailure) as exc:
        await _split(b"not a pdf", [1], get_settings())
    assert exc.value.code == "ocr_invalid_pdf"
