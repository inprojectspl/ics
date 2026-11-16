"""Binding-scoped results in the shared committed publication receipt store."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain_errors import ConflictError
from app.models import Asset, GitLabBinding, PublicationReceipt
from app.services.publications import SCHEMA_VERSION

if TYPE_CHECKING:
    from app.services.asset_versions import NewVersion


@dataclass(frozen=True)
class BindingPublication:
    binding_id: UUID
    release_id: str
    generation: int
    payload_hash: str
    commit_sha: str
    receipt_id: UUID = field(default_factory=uuid4)


async def replay_or_admit(
    session: AsyncSession, binding: GitLabBinding, publication: BindingPublication
) -> dict | None:
    """Called under the binding row lock held through the central version commit."""
    receipt = await session.scalar(
        select(PublicationReceipt).where(
            PublicationReceipt.binding_id == binding.id,
            PublicationReceipt.publication_id == publication.release_id,
        )
    )
    if receipt is not None:
        if (
            receipt.schema_version != SCHEMA_VERSION
            or receipt.payload_hash != publication.payload_hash
            or receipt.asset_id != binding.asset_id
        ):
            raise ConflictError("publication_conflict", "release ID belongs to another intent")
        return receipt.result
    if (
        binding.last_release_generation is not None
        and publication.generation <= binding.last_release_generation
    ):
        raise ConflictError("release_generation_conflict", "release generation is not newer")
    return None


def record_result(
    session: AsyncSession, publication: BindingPublication, asset: Asset, version: NewVersion
) -> dict:
    """Add the immutable HTTP result before the existing version transaction commits."""
    result = {
        "version": version.version,
        "entry_path": version.entry_path,
        "file_count": version.file_count,
        "size_bytes": version.size_bytes,
        "commit_sha": publication.commit_sha,
        "security_status": asset.security_status,
        "receipt": {
            "id": str(publication.receipt_id),
            "schema_version": SCHEMA_VERSION,
            "binding_id": str(publication.binding_id),
            "release_id": publication.release_id,
            "release_generation": publication.generation,
            "payload_hash": publication.payload_hash,
            "asset_id": str(asset.id),
            "version": version.version,
        },
    }
    session.add(
        PublicationReceipt(
            id=publication.receipt_id,
            principal_id=None,
            binding_id=publication.binding_id,
            project_id=asset.project_id,
            order_id=str(publication.binding_id),
            role="binding_sync",
            publication_id=publication.release_id,
            schema_version=SCHEMA_VERSION,
            payload_hash=publication.payload_hash,
            asset_id=asset.id,
            version=version.version,
            result=result,
        )
    )
    return result
