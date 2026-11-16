"""Read a committed publication result after a lost acknowledgement."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser
from app.db import get_session
from app.domain_errors import NotFoundError
from app.services.publications import PublicationScope, authorize_receipt, find_receipt

from ._router import router


@router.get("/publications/{publication_id}")
async def read_publication(
    publication_id: Annotated[str, Path(min_length=1, max_length=200)],
    order_id: Annotated[str, Query(min_length=1, max_length=200)],
    role: Annotated[str, Query(min_length=1, max_length=100)],
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    project_id: UUID | None = None,
) -> dict:
    scope = PublicationScope(user.id, project_id, order_id, role, publication_id)
    receipt = await find_receipt(session, scope)
    if receipt is None:
        raise NotFoundError("publication_not_found", "publication not found")
    await authorize_receipt(session, receipt, user)
    return {
        "publication_id": receipt.publication_id,
        "project_id": str(receipt.project_id) if receipt.project_id else None,
        "order_id": receipt.order_id,
        "role": receipt.role,
        "schema_version": receipt.schema_version,
        "payload_hash": receipt.payload_hash,
        "asset_id": str(receipt.asset_id),
        "version": receipt.version,
        "result": receipt.result,
    }
