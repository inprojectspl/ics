"""Package file rules: safe, canonical paths in the allowed folders, within
the size limits of the contract. Used by `manifest.load_package`."""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.micro_applications.manifest import Package

_TOP_LEVEL = ("public/", "handlers/", "source/", "seed/")
_ALLOWED_SINGLE = frozenset({"microapp.json", "tests/fixtures.json", "README.md"})
_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]+$")


def normalize_path(raw: str) -> str | None:
    """The canonical package path, or None when it is unsafe."""
    if not isinstance(raw, str) or not raw or len(raw) > 200:
        return None
    path = unicodedata.normalize("NFC", raw)
    if path.startswith("/") or "\\" in path or any(ord(c) < 0x20 or ord(c) == 0x7F for c in path):
        return None
    parts = path.split("/")
    if any(p in ("", ".", "..") or not _SEGMENT.match(p) or p.startswith(".") for p in parts):
        return None
    return path


def check_paths(pkg: Package, raw_files: list[tuple[str, bytes]]) -> None:
    seen: dict[str, str] = {}
    for raw, data in raw_files:
        path = normalize_path(raw)
        if path is None:
            pkg.error("path_invalid", f"unsafe or invalid path: {raw!r}", file=str(raw)[:200])
            continue
        folded = path.casefold()
        if folded in seen:
            pkg.error("path_duplicate", f"duplicate path after normalization: {path}", file=path)
            continue
        seen[folded] = path
        if path not in _ALLOWED_SINGLE and not path.startswith(_TOP_LEVEL):
            pkg.error(
                "path_not_allowed",
                "files go to microapp.json, public/, handlers/, source/, seed/, tests/fixtures.json or README.md",
                file=path,
            )
            continue
        if path.startswith("handlers/") and not path.endswith(".mjs"):
            pkg.error("handler_extension", "handlers must be .mjs modules", file=path)
        if path.startswith("source/") and not path.endswith(".ts"):
            pkg.error("source_extension", "source/ holds TypeScript sources only", file=path)
        if path.startswith("seed/") and not path.endswith(".json"):
            pkg.error("seed_extension", "seed/ holds <collection>.json files only", file=path)
        pkg.files[path] = data
    from app.services.micro_applications.manifest import LIMITS, MANIFEST_PATH

    if len(pkg.files) > LIMITS["max_files"]:
        pkg.error("package_too_many_files", f"at most {LIMITS['max_files']} files", file="")
    if pkg.total_bytes > LIMITS["max_package_bytes"]:
        pkg.error("package_too_large", f"at most {LIMITS['max_package_bytes']} bytes", file="")
    handler_bytes = sum(len(b) for p, b in pkg.files.items() if p.startswith("handlers/"))
    if handler_bytes > LIMITS["max_handler_bytes"]:
        pkg.error(
            "handlers_too_large", f"handler code is limited to {LIMITS['max_handler_bytes']} bytes"
        )
    for p, b in pkg.files.items():
        if p.startswith("handlers/") or p == MANIFEST_PATH:
            try:
                b.decode("utf-8")
            except UnicodeDecodeError:
                pkg.error("not_utf8", "must be UTF-8 text", file=p)
