from pathlib import Path

import pytest

from app.storage import FSStorage


async def _gen(chunks: list[bytes]):
    for c in chunks:
        yield c


@pytest.mark.asyncio
async def test_put_and_get_roundtrip(tmp_path: Path):
    s = FSStorage(tmp_path)
    size = await s.put("assets/abc/v1/file.md", _gen([b"hello ", b"world"]))
    assert size == 11
    stream = await s.get("assets/abc/v1/file.md")
    out = b"".join([c async for c in stream])
    assert out == b"hello world"


@pytest.mark.asyncio
async def test_traversal_rejected(tmp_path: Path):
    s = FSStorage(tmp_path)
    with pytest.raises(ValueError):
        await s.put("../etc/passwd", _gen([b"x"]))
    with pytest.raises(ValueError):
        await s.put("/abs/path", _gen([b"x"]))


@pytest.mark.asyncio
async def test_delete_prefix(tmp_path: Path):
    s = FSStorage(tmp_path)
    await s.put("assets/abc/v1/a.md", _gen([b"a"]))
    await s.put("assets/abc/v1/b.md", _gen([b"b"]))
    assert await s.exists("assets/abc/v1/a.md")
    await s.delete_prefix("assets/abc")
    assert not await s.exists("assets/abc/v1/a.md")
