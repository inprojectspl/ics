"""Shared file upload pipeline for the collection and HTML bundle uploads.
Routes prepare the `(file, rel_path)` pairs; this module uploads them under a
fresh `assets/{slug}/v1`, enforces the size, bundle and quota limits and wipes
the whole prefix if anything fails.
"""

from __future__ import annotations

import asyncio
import io
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app import quota
from app.config import Settings
from app.domain_errors import InvalidInputError, LimitExceededError
from app.models import User
from app.slug import generate_slug
from app.storage import storage_from_url

_UPLOAD_CONCURRENCY = 8

# Chunk size for reading a multipart file: 64KB balances the number of I/O
# round trips against memory footprint.
_CHUNK_BYTES = 64 * 1024


class ReadableFile(Protocol):
    """What the pipeline needs from an upload: FastAPI's `UploadFile`
    satisfies it, and so does any test double with an async `read`."""

    async def read(self, size: int = -1) -> bytes: ...


class BytesFile:
    """`ReadableFile` over bytes already in memory, such as content decoded
    from a JSON request."""

    def __init__(self, data: bytes) -> None:
        self._buf = io.BytesIO(data)

    async def read(self, size: int = -1) -> bytes:
        return self._buf.read(size)


class ByteBudget:
    """Byte allowance shared by every file of one upload, so an oversized
    request is cut off while streaming instead of after it hit storage."""

    def __init__(
        self, limit: int, message: str = "asset too large", code: str = "upload_too_large"
    ) -> None:
        self.limit = limit
        self.used = 0
        self.message = message
        self.code = code

    def consume(self, n: int) -> None:
        self.used += n
        if self.used > self.limit:
            raise LimitExceededError(self.code, self.message)


async def one_chunk(data: bytes) -> AsyncIterator[bytes]:
    """A finite buffer in the `AsyncIterator[bytes]` shape `Storage.put` takes."""
    yield data


async def chunked(file: ReadableFile, budget: ByteBudget | None = None) -> AsyncIterator[bytes]:
    while chunk := await file.read(_CHUNK_BYTES):
        if budget is not None:
            budget.consume(len(chunk))
        yield chunk


async def put_all(
    storage, prefix: str, pairs: Sequence[tuple[ReadableFile, str]], budget: ByteBudget
):
    """Write `(file, rel)` pairs under `prefix` with bounded concurrency.

    Waits for every write to settle before reporting a failure, so the
    caller's cleanup of `prefix` cannot race a write that is still running."""
    sem = asyncio.Semaphore(_UPLOAD_CONCURRENCY)

    async def _put_one(file: ReadableFile, rel: str) -> tuple[str, int]:
        async with sem:
            size = await storage.put(f"{prefix}/{rel}", chunked(file, budget))
        return rel, size

    outcomes = await asyncio.gather(*(_put_one(f, r) for f, r in pairs), return_exceptions=True)
    for outcome in outcomes:
        if isinstance(outcome, BaseException):
            raise outcome
    return outcomes


@dataclass(frozen=True)
class StagedUpload:
    """Staged upload result: slug plus the list of (rel_path, size_bytes)."""

    slug: str
    results: list[tuple[str, int]]
    total_bytes: int
    storage_prefix: str  # `assets/{slug}`: asset root, without `/v1`


async def stage_asset_files(
    pairs: Sequence[tuple[ReadableFile, str]],
    *,
    user: User,
    settings: Settings,
    session: AsyncSession,
    size_limit_message: str = "asset too large",
    bundle_max_bytes: int | None = None,
) -> StagedUpload:
    """Upload the pairs under a fresh `assets/{slug}/v1`. Every error path
    (limits, quota, storage) wipes `assets/{slug}`, so no orphaned files are
    left without a DB record."""
    slug = generate_slug()
    storage = storage_from_url(settings.storage_url)
    storage_prefix = f"assets/{slug}"
    version_prefix = f"{storage_prefix}/v1"
    budget = ByteBudget(settings.max_asset_bytes, size_limit_message)

    try:
        results = await put_all(storage, version_prefix, pairs, budget)
    except Exception:
        # Any storage error (S3, FS, network) can leave files behind; re-raised.
        await storage.delete_prefix(storage_prefix)
        raise

    total = sum(s for _, s in results)
    try:
        if bundle_max_bytes is not None:
            quota.assert_bundle_fits(total_bytes=total, bundle_max_bytes=bundle_max_bytes)
        await quota.assert_can_grow(
            session,
            user.id,
            incoming_bytes=total,
            quota_bytes=user.storage_quota_bytes,
        )
    except quota.QuotaExceededError:
        await storage.delete_prefix(storage_prefix)
        raise

    return StagedUpload(
        slug=slug,
        results=results,
        total_bytes=total,
        storage_prefix=storage_prefix,
    )


def validate_pairs_count(
    files: Sequence[ReadableFile],
    paths: list[str],
    *,
    settings: Settings,
) -> None:
    """Early validation before upload: refuse the request before touching
    storage. Shared by collection/html_bundle."""
    if len(files) != len(paths):
        raise InvalidInputError("files_paths_mismatch", "files/paths length mismatch")
    if len(files) > settings.max_files_per_bundle:
        raise LimitExceededError("bundle_too_many_files", "too many files")
