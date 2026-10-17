"""Safe-extract guardrails for GitLab binding sync.

These cover the security-critical path: only signature-trusted bundles
get here, but a compromised CI build could still craft a malicious tarball.
"""

import io
import tarfile
from pathlib import Path

import pytest

from app.bundle_extract import extract_to_storage
from app.domain_errors import DomainError
from app.errors import domain_status
from app.storage import FSStorage


def _make_tar_gz(entries: dict[str, bytes], *, force_links: bool = False) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name, data in entries.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
        if force_links:
            link_info = tarfile.TarInfo(name="link")
            link_info.type = tarfile.SYMTYPE
            link_info.linkname = "/etc/passwd"
            t.addfile(link_info)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_extract_writes_files(tmp_path: Path):
    storage = FSStorage(tmp_path)
    bundle = _make_tar_gz(
        {
            "README.md": b"# Hello\n",
            "Notes/page.md": b"# Page\n",
        }
    )
    written, total = await extract_to_storage(
        bundle_bytes=bundle,
        storage=storage,
        dest_prefix="a/v2",
        max_files=100,
        max_total_bytes=10_000,
    )
    assert sorted(written) == ["Notes/page.md", "README.md"]
    assert total == len(b"# Hello\n") + len(b"# Page\n")
    assert (tmp_path / "a/v2/README.md").read_bytes() == b"# Hello\n"
    assert (tmp_path / "a/v2/Notes/page.md").read_bytes() == b"# Page\n"


@pytest.mark.asyncio
async def test_extract_rejects_path_traversal(tmp_path: Path):
    storage = FSStorage(tmp_path)
    bundle = _make_tar_gz({"../escape.md": b"x"})
    with pytest.raises(DomainError) as exc:
        await extract_to_storage(
            bundle_bytes=bundle,
            storage=storage,
            dest_prefix="a/v1",
            max_files=10,
            max_total_bytes=1000,
        )
    assert domain_status(exc.value) == 400


@pytest.mark.asyncio
async def test_extract_rejects_absolute_path(tmp_path: Path):
    storage = FSStorage(tmp_path)
    bundle = _make_tar_gz({"/etc/passwd": b"hi"})
    with pytest.raises(DomainError) as exc:
        await extract_to_storage(
            bundle_bytes=bundle,
            storage=storage,
            dest_prefix="a/v1",
            max_files=10,
            max_total_bytes=1000,
        )
    assert domain_status(exc.value) == 400


@pytest.mark.asyncio
async def test_extract_rejects_symlinks(tmp_path: Path):
    storage = FSStorage(tmp_path)
    bundle = _make_tar_gz({"a.md": b"x"}, force_links=True)
    with pytest.raises(DomainError):
        await extract_to_storage(
            bundle_bytes=bundle,
            storage=storage,
            dest_prefix="a/v1",
            max_files=10,
            max_total_bytes=1000,
        )


@pytest.mark.asyncio
async def test_extract_caps_file_count(tmp_path: Path):
    storage = FSStorage(tmp_path)
    bundle = _make_tar_gz({f"f{i}.md": b"x" for i in range(10)})
    with pytest.raises(DomainError) as exc:
        await extract_to_storage(
            bundle_bytes=bundle,
            storage=storage,
            dest_prefix="a/v1",
            max_files=5,
            max_total_bytes=10_000,
        )
    assert domain_status(exc.value) == 413


@pytest.mark.asyncio
async def test_extract_caps_total_size(tmp_path: Path):
    storage = FSStorage(tmp_path)
    bundle = _make_tar_gz({"big.md": b"x" * 5000})
    with pytest.raises(DomainError) as exc:
        await extract_to_storage(
            bundle_bytes=bundle,
            storage=storage,
            dest_prefix="a/v1",
            max_files=10,
            max_total_bytes=1000,
        )
    assert domain_status(exc.value) == 413


@pytest.mark.asyncio
async def test_extract_rejects_non_targz(tmp_path: Path):
    storage = FSStorage(tmp_path)
    with pytest.raises(DomainError) as exc:
        await extract_to_storage(
            bundle_bytes=b"this is not a tar.gz",
            storage=storage,
            dest_prefix="a/v1",
            max_files=10,
            max_total_bytes=1000,
        )
    assert domain_status(exc.value) == 400


@pytest.mark.asyncio
async def test_extract_rejects_truncated_targz(tmp_path: Path):
    # A cut-off gzip stream opens fine and fails only while reading members,
    # with EOFError rather than a TarError; it must still be a 400.
    bundle = _make_tar_gz({f"f{i}.md": bytes(range(256)) * 20 for i in range(20)})
    with pytest.raises(DomainError) as exc:
        await extract_to_storage(
            bundle_bytes=bundle[: len(bundle) // 2],
            storage=FSStorage(tmp_path),
            dest_prefix="a/v1",
            max_files=100,
            max_total_bytes=10**7,
        )
    assert domain_status(exc.value) == 400


@pytest.mark.asyncio
async def test_extract_skips_git_metadata(tmp_path: Path):
    # A CI checkout of `source: .` ships .git/ (history, job token in config)
    # and submodule .git files; none of it may reach storage or the quota.
    bundle = _make_tar_gz(
        {
            ".git/config": b"[remote] url = https://gitlab-ci-token:x@example.com/r.git",
            ".git/objects/ab/cdef": b"blob",
            "vendor/lib/.git": b"gitdir: ../../.git/modules/lib",
            "docs/.gitignore": b"*.tmp",
            "README.md": b"# Hello",
        }
    )
    written, total = await extract_to_storage(
        bundle_bytes=bundle,
        storage=FSStorage(tmp_path),
        dest_prefix="a/v1",
        max_files=2,
        max_total_bytes=10_000,
    )
    assert sorted(written) == ["README.md", "docs/.gitignore"]
    assert total == len(b"# Hello") + len(b"*.tmp")
    assert not (tmp_path / "a/v1/.git").exists()
