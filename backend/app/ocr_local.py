"""Local OCR of PDF pages: pdfium renders, RapidOCR on ONNX/CPU reads (ADR-0021).

A killable child process (`python -m app.ocr_local`, PDF on stdin) like
`pdf_extract`. Stdout is JSON lines so the parent sees progress and stuck pages:
`{"engine"}` once, `{"page", "text"}` per page, then `{"done"}`, or `{"error"}`.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from collections.abc import Sequence
from typing import Any

from app.pdf_extract import clean_text, limit_resources

# A box belongs to the current line when its vertical centre falls inside
# the line's band; a gap above this many line heights starts a paragraph.
_PARAGRAPH_GAP = 1.2

Box = Sequence[Sequence[float]]


def layout_text(items: Sequence[tuple[Box, str]]) -> str:
    """Page text from recognized boxes, joined per visual line and split into
    paragraphs by vertical gaps; otherwise a label and its value land on two lines."""
    boxes = []
    for box, text in items:
        text = text.strip()
        if text:
            ys = [p[1] for p in box]
            boxes.append((min(ys), max(ys), min(p[0] for p in box), text))
    if not boxes:
        return ""
    boxes.sort(key=lambda b: (b[0] + b[1]) / 2)
    # A line is [top, bottom, [(left, text), ...]], its band grown box by box.
    lines: list[list[Any]] = []
    for top, bottom, left, text in boxes:
        current = lines[-1] if lines else None
        if current is not None and current[0] <= (top + bottom) / 2 <= current[1]:
            current[0], current[1] = min(current[0], top), max(current[1], bottom)
            current[2].append((left, text))
        else:
            lines.append([top, bottom, [(left, text)]])

    heights = sorted(bottom - top for top, bottom, _ in lines)
    typical = heights[len(heights) // 2] or 1.0
    out: list[str] = []
    previous_bottom: float | None = None
    for top, bottom, runs in lines:
        if previous_bottom is not None and top - previous_bottom > _PARAGRAPH_GAP * typical:
            out.append("")
        out.append(" ".join(text for _, text in sorted(runs)))
        previous_bottom = bottom
    return clean_text("\n".join(out))


def render_scale(width_pt: float, height_pt: float, *, dpi: int, max_pixels: int) -> float:
    """pdfium scale for a page: `dpi`, lowered so the bitmap stays under
    `max_pixels` (a page can declare any size; A0 at 200 dpi is 50 MP)."""
    scale = dpi / 72
    area = width_pt * height_pt * scale * scale
    if area > max_pixels > 0 and width_pt > 0 and height_pt > 0:
        scale = math.sqrt(max_pixels / (width_pt * height_pt))
    return scale


def _emit(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _engine(threads: int) -> tuple[Any, str]:  # pragma: no cover - needs the models
    import importlib.metadata

    import cv2
    from rapidocr import RapidOCR

    # OpenCV keeps its own thread pool, sized to the CPU count otherwise.
    cv2.setNumThreads(threads)

    engine = RapidOCR(
        params={
            "Global.log_level": "error",
            "EngineConfig.onnxruntime.intra_op_num_threads": threads,
            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
        }
    )
    return engine, f"rapidocr {importlib.metadata.version('rapidocr')}"


def recognize(
    data: bytes, pages: Sequence[int], *, dpi: int, max_pixels: int, threads: int
) -> None:  # pragma: no cover - exercised through the subprocess
    import numpy as np
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(data)
    except Exception:
        _emit({"error": "ocr_invalid_pdf"})
        return
    engine, name = _engine(threads)
    _emit({"engine": name})
    count = len(pdf)
    for number in pages:
        text = ""
        if 1 <= number <= count:
            try:
                page = pdf[number - 1]
                width, height = page.get_size()
                scale = render_scale(width, height, dpi=dpi, max_pixels=max_pixels)
                image = np.asarray(page.render(scale=scale, grayscale=True).to_pil())
                result = engine(image)
                if result.boxes is not None and result.txts:
                    text = layout_text(list(zip(result.boxes.tolist(), result.txts, strict=False)))
            except MemoryError:
                raise
            except Exception:
                # One unreadable page must not cost the rest of the document.
                text = ""
        _emit({"page": number, "text": text})
    _emit({"done": True})


def main(argv: list[str]) -> int:  # pragma: no cover - exercised through the subprocess
    parser = argparse.ArgumentParser(prog="app.ocr_local")
    parser.add_argument("--pages", required=True, help="comma separated 1-based page numbers")
    parser.add_argument("--dpi", type=int, required=True)
    parser.add_argument("--max-pixels", type=int, required=True)
    parser.add_argument("--threads", type=int, required=True)
    parser.add_argument("--memory", type=int, required=True)
    args = parser.parse_args(argv)
    limit_resources(args.memory)
    logging.disable(logging.WARNING)
    pages = [int(p) for p in args.pages.split(",") if p]
    data = sys.stdin.buffer.read()
    try:
        recognize(
            data, pages, dpi=args.dpi, max_pixels=args.max_pixels, threads=max(1, args.threads)
        )
    except MemoryError:
        _emit({"error": "ocr_out_of_memory"})
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
