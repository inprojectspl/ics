"""Tests for `services/upload.py`, the shared upload pipeline.

We use a temporary FS storage (`fs:///tmp/test-...`) instead of S3 to avoid
mocks and exercise the real put/delete_prefix path.
"""

from __future__ import annotations

import io
import tempfile
from pathlib import Path

import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers

from app.config import Settings
from app.domain_errors import DomainError
from app.errors import domain_status
from app.services.upload import (
    chunked,
    stage_asset_files,
    validate_pairs_count,
)
from tests.conftest import mk_user


def _settings_with_storage(
    tmp_dir: str, *, max_bytes: int = 10 * 1024 * 1024, max_files: int = 100
) -> Settings:
    s = Settings()
    s.storage_url = f"fs://{tmp_dir}"
    s.max_asset_bytes = max_bytes
    s.max_files_per_bundle = max_files
    return s


def _upload_file(name: str, content: bytes) -> UploadFile:
    """Build an `UploadFile` from synthetic content."""
    return UploadFile(
        filename=name,
        file=io.BytesIO(content),
        headers=Headers({"content-type": "text/plain"}),
    )


@pytest.mark.asyncio
async def test_chunked_yields_64kb_chunks():
    data = b"x" * (64 * 1024 * 2 + 100)
    file = _upload_file("big.bin", data)
    chunks = []
    async for chunk in chunked(file):
        chunks.append(chunk)
    # 2 full chunks + tail.
    assert len(chunks) >= 2
    assert sum(len(c) for c in chunks) == len(data)


@pytest.mark.asyncio
async def test_chunked_empty_file():
    file = _upload_file("empty", b"")
    chunks = [c async for c in chunked(file)]
    assert chunks == []


def test_validate_passes_for_matching_lengths():
    s = Settings()
    s.max_files_per_bundle = 10
    # No exception means OK.
    validate_pairs_count(
        [_upload_file("a", b"x"), _upload_file("b", b"y")],
        ["a.md", "b.md"],
        settings=s,
    )


def test_validate_rejects_length_mismatch():
    s = Settings()
    s.max_files_per_bundle = 10
    with pytest.raises(DomainError) as exc:
        validate_pairs_count(
            [_upload_file("a", b"x")],
            ["a.md", "b.md"],
            settings=s,
        )
    assert domain_status(exc.value) == 400


def test_validate_rejects_too_many_files():
    s = Settings()
    s.max_files_per_bundle = 2
    files = [_upload_file(f"f{i}", b"x") for i in range(3)]
    paths = [f"f{i}.md" for i in range(3)]
    with pytest.raises(DomainError) as exc:
        validate_pairs_count(files, paths, settings=s)
    assert domain_status(exc.value) == 413


@pytest.mark.asyncio
async def test_stage_asset_files_uploads_and_returns_slug(session):
    user = await mk_user(session)
    await session.commit()

    with tempfile.TemporaryDirectory() as tmp:
        s = _settings_with_storage(tmp)
        pairs = [
            (_upload_file("a.md", b"hello"), "a.md"),
            (_upload_file("b.md", b"world"), "b.md"),
        ]
        result = await stage_asset_files(
            pairs,
            user=user,
            settings=s,
            session=session,
        )
        assert result.slug
        assert len(result.results) == 2
        assert result.total_bytes == len(b"hello") + len(b"world")
        # Files were actually written.
        files_on_disk = list(Path(tmp).rglob("*.md"))
        assert len(files_on_disk) == 2


@pytest.mark.asyncio
async def test_stage_rejects_when_total_exceeds_size_limit(session):
    user = await mk_user(session)
    await session.commit()

    with tempfile.TemporaryDirectory() as tmp:
        s = _settings_with_storage(tmp, max_bytes=10)
        pairs = [(_upload_file("big.md", b"x" * 100), "big.md")]
        with pytest.raises(DomainError) as exc:
            await stage_asset_files(pairs, user=user, settings=s, session=session)
        assert domain_status(exc.value) == 413
        # Cleanup left the storage empty (no orphans).
        leftover = list(Path(tmp).rglob("*"))
        assert all(p.is_dir() or p.stat().st_size == 0 for p in leftover) or not leftover


@pytest.mark.asyncio
async def test_stage_rejects_when_quota_exceeded(session):
    user = await mk_user(session, email_verified=True)
    # Force quota=10; the file has 100 bytes, so 413.
    user.storage_quota_bytes = 10
    await session.commit()

    with tempfile.TemporaryDirectory() as tmp:
        s = _settings_with_storage(tmp, max_bytes=10_000)
        pairs = [(_upload_file("file.md", b"x" * 100), "file.md")]
        with pytest.raises(DomainError) as exc:
            await stage_asset_files(pairs, user=user, settings=s, session=session)
        assert domain_status(exc.value) == 413


@pytest.mark.asyncio
async def test_stage_rejects_when_bundle_cap_exceeded(session):
    """The per-user bundle cap also applies to the multipart path, not only
    to `/html-json`. Otherwise an admin lowers the limit in the panel and the
    user sends the same package through the form."""
    user = await mk_user(session)
    await session.commit()

    with tempfile.TemporaryDirectory() as tmp:
        s = _settings_with_storage(tmp, max_bytes=10_000)
        pairs = [(_upload_file("index.html", b"x" * 100), "index.html")]
        with pytest.raises(DomainError) as exc:
            await stage_asset_files(
                pairs,
                user=user,
                settings=s,
                session=session,
                bundle_max_bytes=10,
            )
        assert domain_status(exc.value) == 413
        # Cleanup: prefix wiped, no orphans left in storage.
        leftover = [p for p in Path(tmp).rglob("*") if p.is_file()]
        assert leftover == []


@pytest.mark.asyncio
async def test_stage_uses_custom_size_limit_message(session):
    user = await mk_user(session)
    await session.commit()

    with tempfile.TemporaryDirectory() as tmp:
        s = _settings_with_storage(tmp, max_bytes=1)
        pairs = [(_upload_file("a.md", b"toomuch"), "a.md")]
        with pytest.raises(DomainError) as exc:
            await stage_asset_files(
                pairs,
                user=user,
                settings=s,
                session=session,
                size_limit_message="bundle too large",
            )
        assert domain_status(exc.value) == 413
        assert exc.value.detail == "bundle too large"
