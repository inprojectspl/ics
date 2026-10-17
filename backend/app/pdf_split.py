"""A PDF of selected pages of another, for OCR engines that take a file per
request (ADR-0021). A child process like `pdf_extract`, since pdfium parses
untrusted bytes: `python -m app.pdf_split --pages 3,4,9`, PDF in and out.
"""

from __future__ import annotations

import argparse
import io
import sys

from app.pdf_extract import limit_resources


def split(data: bytes, pages: list[int]) -> bytes:
    """The pages (1-based, in the given order) as a new PDF."""
    import pypdfium2 as pdfium

    source = pdfium.PdfDocument(data)
    target = pdfium.PdfDocument.new()
    target.import_pages(source, [p - 1 for p in pages])
    out = io.BytesIO()
    target.save(out)
    return out.getvalue()


def main(argv: list[str]) -> int:  # pragma: no cover - exercised through the subprocess
    parser = argparse.ArgumentParser(prog="app.pdf_split")
    parser.add_argument("--pages", required=True)
    parser.add_argument("--memory", type=int, required=True)
    args = parser.parse_args(argv)
    limit_resources(args.memory)
    pages = [int(p) for p in args.pages.split(",") if p]
    try:
        sys.stdout.buffer.write(split(sys.stdin.buffer.read(), pages))
    except Exception:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
