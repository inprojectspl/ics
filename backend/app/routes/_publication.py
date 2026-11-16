"""Shared publication identity and multipart payload normalization."""

import hashlib
from collections.abc import Sequence

from fastapi import UploadFile
from pydantic import BaseModel, ConfigDict, Field

from app.errors import ApiError


class PublicationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    order_id: str = Field(min_length=1, max_length=200, pattern=r"^[^\x00-\x20\x7f]+$")
    role: str = Field(min_length=1, max_length=100, pattern=r"^[^\x00-\x20\x7f]+$")


async def upload_digests(pairs: Sequence[tuple[UploadFile, str]]) -> list[dict[str, str]]:
    """Hash accepted paths and bytes without buffering another copy or staging.

    UploadFile is already spooled by the multipart parser. Rewind each stream
    so the normal upload stage remains its only writer.
    """
    seen: set[str] = set()
    result = []
    for file, path in pairs:
        if path in seen:
            raise ApiError(400, "duplicate_path", f"duplicate path: {path}")
        seen.add(path)
        digest = hashlib.sha256()
        try:
            while chunk := await file.read(1024 * 1024):
                digest.update(chunk)
        finally:
            await file.seek(0)
        result.append({"path": path, "sha256": digest.hexdigest()})
    return sorted(result, key=lambda item: item["path"])
