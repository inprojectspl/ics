import asyncio
import shutil
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import urlparse

import aiofiles
import aiofiles.os


class Storage(ABC):
    @abstractmethod
    async def put(self, key: str, data: AsyncIterator[bytes]) -> int: ...

    @abstractmethod
    async def get(self, key: str) -> AsyncIterator[bytes]: ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Remove a single object. Idempotent: missing key is not an error
        (matches the per-file rmtree-style semantics of delete_prefix)."""

    @abstractmethod
    async def delete_prefix(self, prefix: str) -> None: ...

    @abstractmethod
    async def exists(self, key: str) -> bool: ...

    @abstractmethod
    async def list_prefix_stats(self, prefix: str) -> list[tuple[str, int]]:
        """Sorted `(key, size_bytes)` pairs of files under `prefix`, sized from
        the listing itself (no per-object HEADs)."""

    async def list_prefix(self, prefix: str) -> list[str]:
        """Sorted keys under `prefix`."""
        return [key for key, _ in await self.list_prefix_stats(prefix)]

    @abstractmethod
    async def copy_prefix(self, src_prefix: str, dst_prefix: str) -> int:
        """Copy every key under src_prefix to dst_prefix preserving relative
        paths. Returns total bytes copied."""


async def read_all(storage: Storage, key: str) -> bytes:
    """Whole object as bytes. Raises FileNotFoundError when it is missing."""
    buf = bytearray()
    async for chunk in await storage.get(key):
        buf.extend(chunk)
    return bytes(buf)


class FSStorage(Storage):
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _abs(self, key: str) -> Path:
        # One check catches `..`, absolute paths and symlink escapes.
        candidate = (self.root / key).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as e:
            raise ValueError(f"invalid storage key: {key}") from e
        return candidate

    async def put(self, key: str, data: AsyncIterator[bytes]) -> int:
        path = self._abs(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        async with aiofiles.open(path, "wb") as f:
            async for chunk in data:
                await f.write(chunk)
                size += len(chunk)
        return size

    async def get(self, key: str) -> AsyncIterator[bytes]:
        path = self._abs(key)
        # Raise FileNotFoundError on `await get()`, not on first iteration.
        if not path.is_file():
            raise FileNotFoundError(key)

        async def gen():
            async with aiofiles.open(path, "rb") as f:
                while chunk := await f.read(64 * 1024):
                    yield chunk

        return gen()

    async def delete(self, key: str) -> None:
        path = self._abs(key)
        try:
            await aiofiles.os.remove(path)
        except FileNotFoundError:
            pass

    async def delete_prefix(self, prefix: str) -> None:
        path = self._abs(prefix)
        await asyncio.to_thread(shutil.rmtree, path, ignore_errors=True)

    async def exists(self, key: str) -> bool:
        return await aiofiles.os.path.exists(self._abs(key))

    async def copy_prefix(self, src_prefix: str, dst_prefix: str) -> int:
        src = self._abs(src_prefix)
        dst = self._abs(dst_prefix)
        if not src.exists():
            raise FileNotFoundError(f"source prefix not found: {src_prefix}")

        def _copy() -> int:
            shutil.copytree(src, dst, dirs_exist_ok=True)
            return sum(p.stat().st_size for p in dst.rglob("*") if p.is_file())

        return await asyncio.to_thread(_copy)

    async def list_prefix_stats(self, prefix: str) -> list[tuple[str, int]]:
        base = self._abs(prefix)
        root_str = str(self.root)

        def _scan() -> list[tuple[str, int]]:
            if not base.exists():
                return []
            return sorted(
                (str(p).removeprefix(root_str + "/"), p.stat().st_size)
                for p in base.rglob("*")
                if p.is_file()
            )

        return await asyncio.to_thread(_scan)


# R2/S3 tolerate this much parallelism comfortably; high enough to hide
# round-trip latency, low enough to stay well inside per-account limits.
_S3_COPY_CONCURRENCY = 16


# S3 requires parts of at least 5 MiB (except the last one).
_S3_PART_BYTES = 8 * 1024 * 1024


def _is_not_found(error) -> bool:
    return error.response.get("Error", {}).get("Code", "") in ("NoSuchKey", "404", "NotFound")


class S3Storage(Storage):
    """S3-compatible backend (tested on Cloudflare R2). Keys are opaque, so no
    traversal check: `..` is literal in an object key."""

    def __init__(
        self,
        bucket: str,
        *,
        endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
        region: str = "auto",
    ) -> None:
        if not bucket:
            raise ValueError("S3Storage requires a non-empty bucket")
        if not endpoint_url:
            raise ValueError(
                "S3Storage requires endpoint_url: set ICS_S3_ENDPOINT_URL "
                "(e.g. https://<account-id>.r2.cloudflarestorage.com for R2)"
            )
        if not access_key_id or not secret_access_key:
            raise ValueError("S3Storage requires access_key_id + secret_access_key")
        self.bucket = bucket
        self._client_kwargs = {
            "service_name": "s3",
            "endpoint_url": endpoint_url,
            "aws_access_key_id": access_key_id,
            "aws_secret_access_key": secret_access_key,
            "region_name": region,
        }

    def _client(self):
        # Local import: aiobotocore is heavy and only S3 deployments need it.
        from aiobotocore.session import get_session

        return get_session().create_client(**self._client_kwargs)

    async def put(self, key: str, data: AsyncIterator[bytes]) -> int:
        # Multipart above one part, so memory holds one part instead of the file.
        buf = bytearray()
        upload_id: str | None = None
        parts: list[dict] = []
        total = 0
        async with self._client() as client:
            try:
                async for chunk in data:
                    buf.extend(chunk)
                    total += len(chunk)
                    if len(buf) >= _S3_PART_BYTES:
                        if upload_id is None:
                            created = await client.create_multipart_upload(
                                Bucket=self.bucket, Key=key
                            )
                            upload_id = created["UploadId"]
                        parts.append(await self._upload_part(client, key, upload_id, parts, buf))
                        buf = bytearray()
                if upload_id is None:
                    await client.put_object(Bucket=self.bucket, Key=key, Body=bytes(buf))
                    return total
                if buf:
                    parts.append(await self._upload_part(client, key, upload_id, parts, buf))
                await client.complete_multipart_upload(
                    Bucket=self.bucket,
                    Key=key,
                    UploadId=upload_id,
                    MultipartUpload={"Parts": parts},
                )
            except BaseException:
                if upload_id is not None:
                    await client.abort_multipart_upload(
                        Bucket=self.bucket, Key=key, UploadId=upload_id
                    )
                raise
        return total

    async def _upload_part(self, client, key: str, upload_id: str, parts: list, buf) -> dict:
        number = len(parts) + 1
        resp = await client.upload_part(
            Bucket=self.bucket, Key=key, UploadId=upload_id, PartNumber=number, Body=bytes(buf)
        )
        return {"PartNumber": number, "ETag": resp["ETag"]}

    async def get(self, key: str) -> AsyncIterator[bytes]:
        # Open eagerly, as FSStorage does, so `await get()` raises FileNotFoundError.
        from botocore.exceptions import ClientError

        async def _open():
            client_cm = self._client()
            client = await client_cm.__aenter__()
            try:
                resp = await client.get_object(Bucket=self.bucket, Key=key)
            except ClientError as e:
                await client_cm.__aexit__(type(e), e, e.__traceback__)
                if _is_not_found(e):
                    raise FileNotFoundError(key) from e
                raise
            return client_cm, resp

        client_cm, resp = await _open()

        async def gen():
            try:
                async for chunk in resp["Body"]:
                    yield chunk
            finally:
                await client_cm.__aexit__(None, None, None)

        return gen()

    async def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        async with self._client() as client:
            try:
                await client.head_object(Bucket=self.bucket, Key=key)
                return True
            except ClientError as e:
                if _is_not_found(e):
                    return False
                raise

    async def list_prefix_stats(self, prefix: str) -> list[tuple[str, int]]:
        stats: list[tuple[str, int]] = []
        async with self._client() as client:
            paginator = client.get_paginator("list_objects_v2")
            async for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                for obj in page.get("Contents", []) or []:
                    stats.append((obj["Key"], int(obj.get("Size", 0))))
        stats.sort()
        return stats

    async def delete(self, key: str) -> None:
        # S3 DeleteObject is silently idempotent: a missing key returns 204.
        async with self._client() as client:
            await client.delete_object(Bucket=self.bucket, Key=key)

    async def delete_prefix(self, prefix: str) -> None:
        async with self._client() as client:
            paginator = client.get_paginator("list_objects_v2")
            batch: list[dict[str, str]] = []

            async def _flush() -> None:
                if not batch:
                    return
                # Snapshot before clearing: the underlying client may
                # serialise the list lazily and our `.clear()` would race.
                payload = list(batch)
                batch.clear()
                await client.delete_objects(
                    Bucket=self.bucket,
                    Delete={"Objects": payload, "Quiet": True},
                )

            directory = prefix.rstrip("/") + "/"
            async for page in paginator.paginate(Bucket=self.bucket, Prefix=directory):
                for obj in page.get("Contents", []) or []:
                    batch.append({"Key": obj["Key"]})
                    # DeleteObjects caps at 1000 keys per request.
                    if len(batch) >= 1000:
                        await _flush()
            await _flush()

    async def copy_prefix(self, src_prefix: str, dst_prefix: str) -> int:
        # Server-side copies, issued concurrently: every content edit copies the
        # whole version tree on the request path.
        # A prefix names a directory: listing `v1` alone would also match `v10`.
        src_norm = src_prefix.rstrip("/") + "/"
        dst_norm = dst_prefix.rstrip("/") + "/"
        src_stats = await self.list_prefix_stats(src_norm)
        if not src_stats:
            raise FileNotFoundError(f"source prefix not found: {src_prefix}")
        sem = asyncio.Semaphore(_S3_COPY_CONCURRENCY)
        async with self._client() as client:

            async def _copy_one(src_key: str) -> None:
                rel = src_key[len(src_norm) :]
                async with sem:
                    await client.copy_object(
                        Bucket=self.bucket,
                        Key=dst_norm + rel,
                        CopySource={"Bucket": self.bucket, "Key": src_key},
                    )

            # TaskGroup, not gather: the first error cancels the rest before the
            # caller cleans up the prefix.
            async with asyncio.TaskGroup() as tg:
                for key, _ in src_stats:
                    tg.create_task(_copy_one(key))
        return sum(size for _, size in src_stats)


# Memoised on the full connection config: call sites build one per file in read
# loops and the constructors are not free.
_STORAGE_CACHE: dict[tuple, Storage] = {}
_STORAGE_CACHE_MAX = 32


def storage_from_url(url: str, settings=None) -> Storage:
    """Storage for a `storage_url`; S3 credentials come from `settings`, never the
    URL, which leaks into logs."""
    parsed = urlparse(url)
    if parsed.scheme == "s3":
        from app.config import get_settings

        s = settings or get_settings()
        cache_key: tuple = (
            url,
            s.s3_endpoint_url,
            s.s3_access_key_id,
            s.s3_secret_access_key,
            s.s3_region,
        )
    else:
        cache_key = (url,)
    cached = _STORAGE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    storage = _build_storage(url, settings)
    # Bounded for callers that cycle through URLs (tests use a temp dir per case).
    if len(_STORAGE_CACHE) >= _STORAGE_CACHE_MAX:
        _STORAGE_CACHE.pop(next(iter(_STORAGE_CACHE)))
    _STORAGE_CACHE[cache_key] = storage
    return storage


def _build_storage(url: str, settings=None) -> Storage:
    parsed = urlparse(url)
    if parsed.scheme == "fs":
        return FSStorage(Path(parsed.path))
    if parsed.scheme == "s3":
        from app.config import get_settings

        s = settings or get_settings()
        # `s3://bucket`, also tolerating `s3:///bucket`; a query string is ignored.
        bucket = parsed.netloc
        if not bucket and parsed.path:
            bucket = parsed.path.lstrip("/").split("/", 1)[0]
        return S3Storage(
            bucket=bucket,
            endpoint_url=s.s3_endpoint_url,
            access_key_id=s.s3_access_key_id,
            secret_access_key=s.s3_secret_access_key,
            region=s.s3_region,
        )
    raise ValueError(f"unsupported storage scheme: {parsed.scheme}")
