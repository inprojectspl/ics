"""S3Storage backend: config validation + factory dispatch + smoke
contract test against a stubbed aiobotocore client.

We don't spin up moto here; the goal is to lock the call shape (which
S3 verbs we call with which kwargs) so a future swap to AWS S3 / MinIO
works on day one. End-to-end tests against a real R2 bucket are not
part of the unit tests.
"""

from __future__ import annotations

import pytest

from app.storage import FSStorage, S3Storage, storage_from_url


def test_factory_fs_scheme(tmp_path):
    s = storage_from_url(f"fs://{tmp_path}")
    assert isinstance(s, FSStorage)


def test_factory_s3_scheme_uses_settings(monkeypatch):
    """`storage_url=s3://bucket` reads connection config from Settings,
    not from the URL itself: credentials must not leak into log lines
    that print storage_url."""
    from types import SimpleNamespace

    cfg = SimpleNamespace(
        s3_endpoint_url="https://acc.r2.cloudflarestorage.com",
        s3_access_key_id="AK",
        s3_secret_access_key="SK",
        s3_region="auto",
    )
    s = storage_from_url("s3://my-bucket", settings=cfg)
    assert isinstance(s, S3Storage)
    assert s.bucket == "my-bucket"
    # endpoint/credentials carry through to the boto-style kwargs dict
    assert s._client_kwargs["endpoint_url"] == "https://acc.r2.cloudflarestorage.com"
    assert s._client_kwargs["aws_access_key_id"] == "AK"
    assert s._client_kwargs["aws_secret_access_key"] == "SK"
    assert s._client_kwargs["region_name"] == "auto"


def test_factory_rejects_unknown_scheme():
    with pytest.raises(ValueError, match="unsupported storage scheme"):
        storage_from_url("gs://bucket")


def test_s3_storage_rejects_empty_bucket():
    with pytest.raises(ValueError, match="non-empty bucket"):
        S3Storage(
            bucket="",
            endpoint_url="https://x",
            access_key_id="a",
            secret_access_key="b",
        )


def test_s3_storage_rejects_missing_endpoint():
    with pytest.raises(ValueError, match="endpoint_url"):
        S3Storage(
            bucket="b",
            endpoint_url="",
            access_key_id="a",
            secret_access_key="b",
        )


def test_s3_storage_rejects_missing_creds():
    with pytest.raises(ValueError, match="access_key_id"):
        S3Storage(
            bucket="b",
            endpoint_url="https://x",
            access_key_id="",
            secret_access_key="s",
        )


class _StubClient:
    """Records the S3 calls our storage layer makes. Returns just enough
    to drive each method through one happy-path execution."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._objects: dict[str, bytes] = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def put_object(self, *, Bucket, Key, Body):
        self.calls.append(("put_object", {"Bucket": Bucket, "Key": Key, "Body": bytes(Body)}))
        self._objects[Key] = bytes(Body)

    async def create_multipart_upload(self, *, Bucket, Key):
        self.calls.append(("create_multipart_upload", {"Key": Key}))
        return {"UploadId": "up-1"}

    async def upload_part(self, *, Bucket, Key, UploadId, PartNumber, Body):
        self.calls.append(("upload_part", {"PartNumber": PartNumber, "size": len(Body)}))
        self._parts = [*getattr(self, "_parts", []), bytes(Body)]
        return {"ETag": f"etag-{PartNumber}"}

    async def complete_multipart_upload(self, *, Bucket, Key, UploadId, MultipartUpload):
        self.calls.append(("complete_multipart_upload", {"Parts": MultipartUpload["Parts"]}))
        self._objects[Key] = b"".join(self._parts)

    async def abort_multipart_upload(self, *, Bucket, Key, UploadId):
        self.calls.append(("abort_multipart_upload", {"Key": Key}))

    async def head_object(self, *, Bucket, Key):
        self.calls.append(("head_object", {"Bucket": Bucket, "Key": Key}))
        if Key not in self._objects:
            from botocore.exceptions import ClientError

            raise ClientError(
                {"Error": {"Code": "NoSuchKey"}, "ResponseMetadata": {}},
                "HeadObject",
            )
        return {"ContentLength": len(self._objects[Key])}

    async def delete_objects(self, *, Bucket, Delete):
        self.calls.append(("delete_objects", {"Bucket": Bucket, "Delete": Delete}))

    async def copy_object(self, *, Bucket, Key, CopySource):
        self.calls.append(("copy_object", {"Bucket": Bucket, "Key": Key, "CopySource": CopySource}))
        src_key = CopySource["Key"] if isinstance(CopySource, dict) else CopySource
        self._objects[Key] = self._objects[src_key]
        return {}

    def get_paginator(self, name: str):
        objs = list(self._objects.items())

        class _Paginator:
            def paginate(self, *, Bucket, Prefix):
                # Single page for simplicity; real S3 paginates at 1000
                async def gen():
                    yield {
                        "Contents": [
                            {"Key": k, "Size": len(v)} for k, v in objs if k.startswith(Prefix)
                        ],
                    }

                return gen()

        return _Paginator()


@pytest.fixture
def stub_storage(monkeypatch):
    """S3Storage that talks to _StubClient instead of real aiobotocore."""
    stub = _StubClient()
    s = S3Storage(
        bucket="b",
        endpoint_url="https://x",
        access_key_id="a",
        secret_access_key="s",
    )
    monkeypatch.setattr(s, "_client", lambda: stub)
    return s, stub


@pytest.mark.asyncio
async def test_put_calls_put_object_with_buffered_body(stub_storage):
    s, stub = stub_storage

    async def src():
        yield b"hello "
        yield b"world"

    n = await s.put("a/v1/x.md", src())
    assert n == 11
    assert stub.calls[0][0] == "put_object"
    assert stub.calls[0][1]["Key"] == "a/v1/x.md"
    assert stub.calls[0][1]["Body"] == b"hello world"


@pytest.mark.asyncio
async def test_exists_translates_NoSuchKey_to_false(stub_storage):
    s, _ = stub_storage
    assert await s.exists("missing") is False


@pytest.mark.asyncio
async def test_exists_returns_true_for_uploaded_key(stub_storage):
    s, _ = stub_storage

    async def src():
        yield b"x"

    await s.put("k", src())
    assert await s.exists("k") is True


@pytest.mark.asyncio
async def test_list_prefix_uses_paginator(stub_storage):
    s, _stub = stub_storage

    async def src():
        yield b"x"

    await s.put("a/1.md", src())
    await s.put("a/2.md", src())
    await s.put("b/3.md", src())
    keys = await s.list_prefix("a/")
    assert keys == ["a/1.md", "a/2.md"]


@pytest.mark.asyncio
async def test_copy_prefix_uses_server_side_copy(stub_storage):
    s, stub = stub_storage

    async def src():
        yield b"hi"

    await s.put("v1/x.md", src())
    await s.put("v1/y.md", src())

    total = await s.copy_prefix("v1", "v2")
    assert total == 4  # two files x 2 bytes
    copy_calls = [c for c in stub.calls if c[0] == "copy_object"]
    assert len(copy_calls) == 2
    assert {c[1]["Key"] for c in copy_calls} == {"v2/x.md", "v2/y.md"}


@pytest.mark.asyncio
async def test_copy_prefix_raises_for_empty_source(stub_storage):
    s, _ = stub_storage
    with pytest.raises(FileNotFoundError):
        await s.copy_prefix("missing", "dst")


@pytest.mark.asyncio
async def test_delete_prefix_batches_calls(stub_storage):
    s, stub = stub_storage

    async def src():
        yield b"x"

    await s.put("a/1.md", src())
    await s.put("a/2.md", src())
    await s.delete_prefix("a/")

    deletes = [c for c in stub.calls if c[0] == "delete_objects"]
    assert len(deletes) == 1
    assert {o["Key"] for o in deletes[0][1]["Delete"]["Objects"]} == {"a/1.md", "a/2.md"}


@pytest.mark.asyncio
async def test_large_put_streams_in_parts_without_one_big_body(stub_storage, monkeypatch):
    from app import storage as storage_mod

    monkeypatch.setattr(storage_mod, "_S3_PART_BYTES", 10)
    s, stub = stub_storage

    async def src():
        for _ in range(5):
            yield b"x" * 6

    n = await s.put("a/v1/big.bin", src())
    assert n == 30
    verbs = [name for name, _ in stub.calls]
    assert "put_object" not in verbs
    assert verbs[0] == "create_multipart_upload"
    assert verbs[-1] == "complete_multipart_upload"
    sizes = [c["size"] for name, c in stub.calls if name == "upload_part"]
    assert sum(sizes) == 30
    assert max(sizes) < 30
    assert stub._objects["a/v1/big.bin"] == b"x" * 30


@pytest.mark.asyncio
async def test_failed_stream_aborts_the_multipart_upload(stub_storage, monkeypatch):
    from app import storage as storage_mod

    monkeypatch.setattr(storage_mod, "_S3_PART_BYTES", 10)
    s, stub = stub_storage

    async def src():
        yield b"x" * 12
        raise RuntimeError("client went away")

    with pytest.raises(RuntimeError):
        await s.put("a/v1/big.bin", src())
    assert stub.calls[-1][0] == "abort_multipart_upload"
    assert "a/v1/big.bin" not in stub._objects


@pytest.mark.asyncio
async def test_copy_prefix_copies_only_its_own_version(stub_storage):
    """`v1` is a directory: listing it as a bare key prefix also matched
    `v10`, whose files landed in the copy under a nested path."""
    s, stub = stub_storage

    async def src(data: bytes):
        yield data

    await s.put("assets/a/v1/x.md", src(b"one"))
    await s.put("assets/a/v10/x.md", src(b"ten!!"))
    await s.put("assets/a/v10/y.md", src(b"ten"))

    total = await s.copy_prefix("assets/a/v1", "assets/a/v11")

    assert total == 3
    copied = {c[1]["Key"] for c in stub.calls if c[0] == "copy_object"}
    assert copied == {"assets/a/v11/x.md"}
    assert await s.list_prefix("assets/a/v10/") == ["assets/a/v10/x.md", "assets/a/v10/y.md"]


@pytest.mark.asyncio
async def test_delete_prefix_leaves_sibling_versions(stub_storage):
    s, stub = stub_storage

    async def src():
        yield b"x"

    await s.put("assets/a/v1/x.md", src())
    await s.put("assets/a/v10/x.md", src())
    await s.delete_prefix("assets/a/v1")

    deletes = [c for c in stub.calls if c[0] == "delete_objects"]
    assert {o["Key"] for d in deletes for o in d[1]["Delete"]["Objects"]} == {"assets/a/v1/x.md"}
