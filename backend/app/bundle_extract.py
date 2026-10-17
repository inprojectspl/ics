"""Safe extraction of a signature-verified tar.gz bundle into storage.

Members are only read via `extractfile`, never written to disk; links, devices and
absolute paths are rejected, names are normalised like uploads, counts and sizes
are capped, and `.git` metadata (history, CI job tokens) is dropped.
"""

from __future__ import annotations

import asyncio
import io
import tarfile
import zlib

from app.collections_io import normalize_collection_path
from app.domain_errors import InvalidInputError, LimitExceededError
from app.services.upload import one_chunk

# Matches the multipart upload path's concurrency.
_WRITE_CONCURRENCY = 8


def _is_git_metadata(name: str) -> bool:
    return ".git" in name.replace("\\", "/").split("/")


def _open_archive(bundle_bytes: bytes) -> tuple[tarfile.TarFile, list[tarfile.TarInfo]]:
    tar = tarfile.open(fileobj=io.BytesIO(bundle_bytes), mode="r:gz")
    return tar, tar.getmembers()


async def extract_to_storage(
    *,
    bundle_bytes: bytes,
    storage,
    dest_prefix: str,
    max_files: int,
    max_total_bytes: int,
) -> tuple[list[str], int]:
    """Returns (rel_paths, total_bytes); on a DomainError the caller cleans up storage."""
    try:
        # Reading the member index decompresses the whole archive: seconds of
        # CPU for a large bundle, so it runs off the event loop.
        tar, all_entries = await asyncio.to_thread(_open_archive, bundle_bytes)
    except (tarfile.TarError, EOFError, OSError, zlib.error) as e:
        # A truncated or corrupt gzip stream fails in getmembers, not in
        # open, and with non-tarfile exceptions.
        raise InvalidInputError("bundle_invalid_archive", f"bundle is not a tar.gz: {e}") from e
    # Reject anything that is not a regular file before looking at quotas:
    # we don't want a symlink-only bundle to silently succeed with 0 writes.
    for m in all_entries:
        if m.islnk() or m.issym() or m.ischr() or m.isblk() or m.isdev() or m.isfifo():
            raise InvalidInputError(
                "bundle_entry_rejected",
                f"rejected entry (link/device): {m.name}",
            )
        if m.name.startswith(("/", "\\")):
            raise InvalidInputError(
                "bundle_entry_rejected",
                f"rejected entry (absolute path): {m.name}",
            )

    members = [m for m in all_entries if m.isfile() and not _is_git_metadata(m.name)]
    if len(members) > max_files:
        raise LimitExceededError("bundle_too_many_files", "too many files")
    if sum(m.size for m in members) > max_total_bytes:
        raise LimitExceededError("bundle_too_large", "bundle too large")

    def _extract_all() -> list[tuple[str, bytes]]:
        out: list[tuple[str, bytes]] = []
        for m in members:
            fh = tar.extractfile(m)
            if fh is None:
                continue
            out.append((normalize_collection_path(m.name), fh.read()))
        return out

    extracted = await asyncio.to_thread(_extract_all)

    sem = asyncio.Semaphore(_WRITE_CONCURRENCY)

    async def _write(rel: str, data: bytes) -> tuple[str, int]:
        async with sem:
            return rel, await storage.put(f"{dest_prefix}/{rel}", one_chunk(data))

    results = await asyncio.gather(*(_write(rel, data) for rel, data in extracted))
    written = [rel for rel, _ in results]
    total = sum(size for _, size in results)

    return written, total
