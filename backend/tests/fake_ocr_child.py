"""Stand-in for `app.ocr_local` in provider tests: speaks the same line
protocol, with the behaviour picked by `FAKE_OCR_MODE`."""

from __future__ import annotations

import json
import os
import sys
import time


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main(argv: list[str]) -> int:
    pages = [int(p) for p in argv[argv.index("--pages") + 1].split(",") if p]
    sys.stdin.buffer.read()
    mode = os.environ.get("FAKE_OCR_MODE", "ok")
    if mode == "error":
        _emit({"error": "ocr_out_of_memory"})
        return 0
    _emit({"engine": "fake 1.0"})
    for number in pages:
        if mode == "hang":
            time.sleep(30)
        if mode == "crash":
            return 1
        if mode == "skip":
            number += 1
        text = f"text of page {number}"
        if mode == "env":
            text = f"{os.environ.get('MALLOC_ARENA_MAX')}/{os.environ.get('OMP_NUM_THREADS')}"
        _emit({"page": number, "text": text})
    if mode != "no_done":
        _emit({"done": True})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
