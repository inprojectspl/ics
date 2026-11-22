"""Publication identity and committed results; no independent reservation state."""

import hashlib
import json
from dataclasses import asdict, dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import permissions
from app.db import advisory_xact_lock
from app.domain_errors import ConflictError, NotFoundError
from app.models import Asset, PublicationReceipt, User

SCHEMA_VERSION = 1


def canonical_hash(value: dict) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PublicationScope:
    principal_id: UUID
    project_id: UUID | None
    order_id: str
    role: str
    publication_id: str


@dataclass(frozen=True)
class VersionPublication:
    scope: PublicationScope
    # Digest of the normalized stage input; the central version writer adds
    # the target, operation, expected version and normalized change note.
    payload_hash: str


async def find_receipt(session: AsyncSession, scope: PublicationScope) -> PublicationReceipt | None:
    return await session.scalar(select(PublicationReceipt).filter_by(**asdict(scope)))


async def authorize_receipt(session: AsyncSession, receipt: PublicationReceipt, user: User) -> None:
    if receipt.principal_id != user.id or receipt.asset_id is None:
        raise NotFoundError("publication_not_found", "publication not found")
    if receipt.project_id is not None:
        await permissions.assert_project_contributor(
            session, user, receipt.project_id, refresh=True
        )
    # Version endpoints may have loaded the asset before the advisory wait.
    # Do not authorize replay from an identity-map snapshot of its old ACL.
    await session.get(Asset, receipt.asset_id, populate_existing=True)
    await permissions.get_viewable_asset_by_id(session, receipt.asset_id, user)


async def lock_and_replay(
    session: AsyncSession, scope: PublicationScope, user: User, payload_hash: str
) -> PublicationReceipt | None:
    # A collision only serializes unrelated scopes. The full unique DB key,
    # never the lock, decides publication identity.
    identity = {
        key: str(value) if isinstance(value, UUID) else value
        for key, value in asdict(scope).items()
    }
    digest = canonical_hash({"publication_scope": identity})
    await advisory_xact_lock(session, f"ics:publication:{digest}")
    receipt = await find_receipt(session, scope)
    if receipt is None:
        # Admission happened before a potentially long wait. Revocation while
        # waiting must prevent a fresh asset as well as refuse receipt replay.
        if scope.project_id is not None:
            await permissions.assert_project_contributor(
                session, user, scope.project_id, refresh=True
            )
        return None
    await authorize_receipt(session, receipt, user)
    if receipt.schema_version != SCHEMA_VERSION or receipt.payload_hash != payload_hash:
        raise ConflictError(
            "publication_conflict", "publication key already belongs to another payload"
        )
    return receipt
