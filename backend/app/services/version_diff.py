"""Comparing two versions of an asset as a list of `FileChange`, one shape for
every kind; only the set of files compared differs. HTML bundle files that do
not decode as UTF-8 are reported as `binary=True` without content or counts.
"""

from __future__ import annotations

import asyncio
import difflib
from dataclasses import asdict, dataclass
from typing import Literal

from app.collections_io import (
    MAX_SLICE_BYTES,
    decode_text,
    list_version_files_with_sizes,
    md_paths,
    read_bytes_at_version,
)
from app.config import Settings
from app.html_bundle import content_type_for, is_text_path
from app.models import Asset

#: Storage read concurrency. A separate constant (not imported from `upload`)
#: because the traffic profile differs: we read two variants of each file; 8
#: is the ceiling S3/MinIO handles without throttling.
_DIFF_READ_CONCURRENCY = 8

#: Above this size we do not count `+N/-M`. Same threshold as partial read
#: (`MAX_SLICE_BYTES`), so "too big to show" and "too big to count" do not
#: drift apart when tuning.
DIFF_COUNT_MAX_BYTES = MAX_SLICE_BYTES

ChangeKind = Literal["added", "removed", "modified"]


class FileNotInEitherVersion(LookupError):
    """The path exists in neither `from_v` nor `to_v`."""


class BinaryFileDiff(ValueError):
    """The file is not text, so there is no line diff for it."""

    def __init__(self, path: str, size_bytes: int) -> None:
        super().__init__(f"binary file: {path}")
        self.path = path
        self.size_bytes = size_bytes
        self.mime = content_type_for(path)


@dataclass(frozen=True)
class FileChange:
    """One summary entry: what happened to a file between versions."""

    path: str
    change: ChangeKind
    binary: bool = False
    #: `None` = not counted (binary file or above `DIFF_COUNT_MAX_BYTES`).
    added_lines: int | None = None
    removed_lines: int | None = None
    size_from: int | None = None
    size_to: int | None = None


def _count_changes(from_text: str, to_text: str) -> tuple[int, int]:
    """`(added, removed)` line counts, without building the diff string.

    `get_opcodes()`, not `ndiff`: ndiff compares every replaced line pair by
    character, thousands of times slower on a rewritten file, and this runs
    synchronously in the event loop. `keepends=True` matches `unified()`, so a
    change to only the final newline is counted too.
    """
    from_lines = from_text.splitlines(keepends=True)
    to_lines = to_text.splitlines(keepends=True)
    added = removed = 0
    matcher = difflib.SequenceMatcher(None, from_lines, to_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "delete"):
            removed += i2 - i1
        if tag in ("replace", "insert"):
            added += j2 - j1
    return added, removed


def unified(from_text: str, to_text: str, from_label: str, to_label: str) -> str:
    """Unified diff of two texts. An empty `from_text`/`to_text` yields an
    "all added" / "all removed" diff; that is how files existing in only one
    of the versions are handled."""
    return "".join(
        difflib.unified_diff(
            from_text.splitlines(keepends=True),
            to_text.splitlines(keepends=True),
            fromfile=from_label,
            tofile=to_label,
            n=3,
        )
    )


def _relevant_paths(asset: Asset, sizes: dict[str, int]) -> set[str]:
    """Which files of a version are considered for the given kind."""
    if asset.kind in ("md_single", "md_collection"):
        return set(md_paths(sorted(sizes)))
    return set(sizes)


def _countable(path: str, size_from: int, size_to: int) -> bool:
    """Whether lines are counted for this file at all, decided from the
    listing before any read. An 80 MB file must not be read and decoded just
    to learn it is "too big"."""
    if max(size_from, size_to) > DIFF_COUNT_MAX_BYTES:
        return False
    return is_text_path(path)


async def diff_summary(
    asset: Asset, from_v: int, to_v: int, settings: Settings
) -> list[FileChange]:
    """List of changes between versions, sorted by path."""
    from_sizes, to_sizes = await asyncio.gather(
        _sizes(asset, from_v, settings), _sizes(asset, to_v, settings)
    )
    from_paths = _relevant_paths(asset, from_sizes)
    to_paths = _relevant_paths(asset, to_sizes)
    sem = asyncio.Semaphore(_DIFF_READ_CONCURRENCY)

    async def _one_sided(path: str, change: ChangeKind) -> FileChange:
        """The file exists in only one version: all its content is added or
        removed, so one read is enough (and only when it can be counted)."""
        version = to_v if change == "added" else from_v
        size = to_sizes[path] if change == "added" else from_sizes[path]
        size_from, size_to = (None, size) if change == "added" else (size, None)
        if not _countable(path, size, size):
            return FileChange(
                path=path,
                change=change,
                binary=not is_text_path(path),
                size_from=size_from,
                size_to=size_to,
            )
        async with sem:
            raw = await read_bytes_at_version(asset, version, path, settings)
        text = decode_text(raw)
        if text is None:
            return FileChange(
                path=path, change=change, binary=True, size_from=size_from, size_to=size_to
            )
        lines = len(text.splitlines())
        return FileChange(
            path=path,
            change=change,
            added_lines=lines if change == "added" else 0,
            removed_lines=lines if change == "removed" else 0,
            size_from=size_from,
            size_to=size_to,
        )

    async def _compare(path: str) -> FileChange | None:
        """The file is in both versions: `None` = unchanged."""
        size_from, size_to = from_sizes[path], to_sizes[path]
        countable = _countable(path, size_from, size_to)
        if size_from != size_to and not countable:
            # A different size already proves a change and nothing would be
            # counted, so skip the read.
            return FileChange(
                path=path,
                change="modified",
                binary=not is_text_path(path),
                size_from=size_from,
                size_to=size_to,
            )
        async with sem:
            from_raw, to_raw = await asyncio.gather(
                read_bytes_at_version(asset, from_v, path, settings),
                read_bytes_at_version(asset, to_v, path, settings),
            )
        if from_raw == to_raw:
            return None
        from_text, to_text = decode_text(from_raw), decode_text(to_raw)
        binary = from_text is None or to_text is None
        added, removed = (
            _count_changes(from_text or "", to_text or "")
            if countable and not binary
            else (None, None)
        )
        return FileChange(
            path=path,
            change="modified",
            binary=binary,
            added_lines=added,
            removed_lines=removed,
            size_from=size_from,
            size_to=size_to,
        )

    results = await asyncio.gather(
        *(_one_sided(p, "added") for p in to_paths - from_paths),
        *(_one_sided(p, "removed") for p in from_paths - to_paths),
        *(_compare(p) for p in from_paths & to_paths),
    )
    return sorted((c for c in results if c is not None), key=lambda c: c.path)


async def _sizes(asset: Asset, version: int, settings: Settings) -> dict[str, int]:
    """Sizes from the storage listing, without per-file HEAD requests."""
    return dict(await list_version_files_with_sizes(asset, version, settings))


def as_payload(changes: list[FileChange]) -> list[dict]:
    """Serialization for the route: the single place where `FileChange`
    becomes JSON."""
    return [asdict(c) for c in changes]


async def file_diff(asset: Asset, from_v: int, to_v: int, path: str, settings: Settings) -> dict:
    """Unified diff of one file; a file missing from one version counts as
    empty. Raises `FileNotInEitherVersion` when it is in neither version and
    `BinaryFileDiff` for a binary file."""

    async def _read(version: int) -> bytes | None:
        try:
            return await read_bytes_at_version(asset, version, path, settings)
        except FileNotFoundError:
            return None

    from_raw, to_raw = await asyncio.gather(_read(from_v), _read(to_v))
    if from_raw is None and to_raw is None:
        raise FileNotInEitherVersion(path)

    from_text = decode_text(from_raw) if from_raw is not None else ""
    to_text = decode_text(to_raw) if to_raw is not None else ""
    if from_text is None or to_text is None:
        raise BinaryFileDiff(path, len(to_raw if to_raw is not None else from_raw or b""))

    change: ChangeKind = (
        "added" if from_raw is None else "removed" if to_raw is None else "modified"
    )
    return {
        "path": path,
        "change": change,
        "diff": unified(from_text, to_text, f"v{from_v}/{path}", f"v{to_v}/{path}"),
    }
