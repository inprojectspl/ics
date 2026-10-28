"""Collection I/O helpers shared by the assets and shares routers."""

from __future__ import annotations

import asyncio
from pathlib import PurePosixPath

from app.config import Settings
from app.constants import DOCUMENT_FILES, AssetKind
from app.domain_errors import InvalidInputError, LimitExceededError
from app.models import Asset
from app.storage import read_all, storage_from_url


def normalize_collection_path(p: str) -> str:
    """Normalize a user-supplied collection-relative path.

    Raises 400 on traversal, absolute paths or empty input.
    """
    cleaned = p.replace("\\", "/").lstrip("/")
    parts = PurePosixPath(cleaned).parts
    if not parts or any(part in ("..", "") for part in parts):
        raise InvalidInputError("invalid_path", f"invalid path: {p}")
    return "/".join(parts)


def upload_basename(raw: str) -> str:
    """Storage name of a single uploaded file: its last path segment. Browsers
    send a base name, other clients may send any path."""
    return normalize_collection_path(PurePosixPath(raw.replace("\\", "/")).name)


#: Shared partial-read limit for MCP-facing endpoints (file-mcp, share
#: resolve). One constant, so clients learn a single pagination protocol.
MAX_LINES_RANGE = 2000

#: Byte cap on the returned slice. Lines do not bound bytes: a minified
#: one-line JS file would pass through whole without this limit.
MAX_SLICE_BYTES = 512 * 1024


def _utf8_exceeds(s: str, cap: int) -> bool:
    """Whether the UTF-8 encoding of `s` exceeds `cap` bytes, without
    encoding on the hot path (bytes >= chars, and UTF-8 is at most 4 B/char)."""
    if len(s) > cap:
        return True
    if len(s) * 4 <= cap:
        return False
    return len(s.encode("utf-8")) > cap


def slice_lines(
    raw: str,
    lines: str | None,
    *,
    max_lines: int = MAX_LINES_RANGE,
    max_bytes: int | None = MAX_SLICE_BYTES,
) -> tuple[str, int, list[int]]:
    """Line-range slice for a partial read (`lines="N-M"`, 1-based inclusive).

    Returns `(content, total_lines, returned_range)`. Refuses rather than truncates:
    400 for a range over `max_lines` (or a long file without `lines`), 413 for a
    slice over `max_bytes`. The caller has already validated the `lines` format.
    """
    all_lines = raw.splitlines()
    total = len(all_lines)
    if lines:
        start_s, end_s = lines.split("-", 1)
        start = max(1, int(start_s))
        end = min(total, int(end_s))
        if end - start + 1 > max_lines:
            raise InvalidInputError(
                "line_range_too_wide",
                f"range too wide (max {max_lines} lines)",
            )
        content, returned_range = "\n".join(all_lines[start - 1 : end]), [start, end]
    else:
        if total > max_lines:
            raise InvalidInputError(
                "file_too_large",
                f"file_too_large (use lines=N-M; total={total})",
            )
        content = "\n".join(all_lines)
        returned_range = [1, total] if total else [0, 0]
    if max_bytes is not None and _utf8_exceeds(content, max_bytes):
        raise LimitExceededError(
            "text_slice_too_large",
            f"text slice too large (max {max_bytes} bytes), narrow it with lines=N-M",
        )
    return content, total, returned_range


def count_line_reads(
    line_sizes: list[int],
    *,
    max_lines: int = MAX_LINES_RANGE,
    max_bytes: int = MAX_SLICE_BYTES,
) -> int:
    """Estimated `slice_lines` reads an agent needs for lines of these UTF-8 sizes;
    a single line over `max_bytes` still counts as one read."""
    reads, in_read, read_bytes = 0, 0, 0
    for size in line_sizes:
        joined = read_bytes + 1 + size if in_read else size
        if in_read and (in_read == max_lines or joined > max_bytes):
            reads, in_read, read_bytes = reads + 1, 1, size
        else:
            in_read, read_bytes = in_read + 1, joined
    return reads + (1 if in_read else 0)


def pick_entry(paths: list[str]) -> str:
    """Pick a collection entry file: shallowest README.md or index.md, else
    alphabetical first."""
    for needle in ("readme.md", "index.md"):
        candidates = [p for p in paths if p.lower() == needle or p.lower().endswith("/" + needle)]
        if candidates:
            candidates.sort(key=lambda p: (p.count("/"), p))
            return candidates[0]
    return sorted(paths, key=lambda p: (p.count("/"), p))[0]


async def read_text(asset: Asset, rel_path: str, settings: Settings) -> str:
    """Read a file from the asset's storage prefix and decode as UTF-8."""
    return await read_text_at_version(asset, asset.version, rel_path, settings)


async def read_bytes_at_version(
    asset: Asset, version: int, rel_path: str, settings: Settings
) -> bytes:
    """Raw bytes of one file at any version (older versions stay in place)."""
    storage = storage_from_url(settings.storage_url)
    return await read_all(storage, f"{asset.storage_prefix}/v{version}/{rel_path}")


def decode_text(raw: bytes) -> str | None:
    """UTF-8 text, or `None` meaning "this is not text".

    Decided by decoding, not the extension: non-UTF-8 text would show garbage in a
    diff or partial read, so it counts as binary.
    """
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


async def read_text_at_version(
    asset: Asset, version: int, rel_path: str, settings: Settings
) -> str:
    """Same as `read_text` but for an arbitrary historical version."""
    raw = await read_bytes_at_version(asset, version, rel_path, settings)
    return raw.decode("utf-8", errors="replace")


async def list_version_files_with_sizes(
    asset: Asset, version: int, settings: Settings
) -> list[tuple[str, int]]:
    """All `(relative_path, size_bytes)` pairs in a version, sorted by path; sizes
    come from the listing, with no per-file HEADs."""
    storage = storage_from_url(settings.storage_url)
    prefix = f"{asset.storage_prefix}/v{version}/"
    stats = await storage.list_prefix_stats(prefix)
    return [(k[len(prefix) :], size) for k, size in stats]


async def list_version_files(asset: Asset, version: int, settings: Settings) -> list[str]:
    """All file paths in a given historical version, sorted."""
    files = await list_version_files_with_sizes(asset, version, settings)
    return [p for p, _ in files]


def md_paths(paths: list[str]) -> list[str]:
    """The collection tree rule (a version's `.md` files), order preserved."""
    return [p for p in paths if p.endswith(".md")]


async def list_md_paths(asset: Asset, settings: Settings) -> list[str]:
    """Return all .md file paths in the collection, sorted."""
    return md_paths(await list_version_files(asset, asset.version, settings))


MarkdownSources = list[tuple[str, str]]
# Bounded so a collection with hundreds of notes cannot open an unbounded
# number of storage connections at once.
_READ_CONCURRENCY = 16


def is_markdown_path(path: str) -> bool:
    """A Markdown file by name: `.md` or `.markdown`, any case."""
    return path.lower().endswith((".md", ".markdown"))


async def read_markdown_files(asset: Asset, settings: Settings) -> MarkdownSources:
    """`(path, text)` of every Markdown file (`.md`, `.markdown`, any case) in the
    current version, in listing order; a file gone since listing is skipped."""
    files = await list_version_files(asset, asset.version, settings)
    rels = [rel for rel in files if is_markdown_path(rel)]
    sem = asyncio.Semaphore(_READ_CONCURRENCY)

    async def _read(rel: str) -> tuple[str, str] | None:
        async with sem:
            try:
                return rel, await read_text_at_version(asset, asset.version, rel, settings)
            except FileNotFoundError:
                return None

    return [src for src in await asyncio.gather(*(_read(r) for r in rels)) if src is not None]


def derive_entry_path(kind: AssetKind, paths: list[str]) -> str:
    """Pick the entry file for an asset kind from a flat list of relative paths.

    Raises InvalidInputError when the paths break the kind's invariants."""
    from app.html_bundle import pick_html_entry  # avoid import cycle

    if kind == "md_collection":
        md = [p for p in paths if p.lower().endswith(".md")]
        if not md:
            raise InvalidInputError("md_files_required", "md_collection expects .md files")
        return pick_entry(md)
    if kind == "md_single":
        md = [p for p in paths if p.lower().endswith(".md")]
        if len(md) != 1:
            raise InvalidInputError(
                "md_single_requires_one_file",
                "md_single expects exactly one .md file",
            )
        return md[0]
    if kind == "html_bundle":
        return pick_html_entry(paths)
    if kind in DOCUMENT_FILES:
        extensions, code = DOCUMENT_FILES[kind]
        if len(paths) != 1 or not paths[0].lower().endswith(extensions):
            raise InvalidInputError(code, f"{kind} expects exactly one document file")
        return paths[0]
    raise InvalidInputError("unsupported_kind", f"unsupported kind: {kind}")
