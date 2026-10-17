"""Optional `doc_type` and `summary` form fields of the multipart upload
endpoints (ADR-0015), validated before the upload touches storage."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Form, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.auth import CurrentUser
from app.db import get_session
from app.services import asset_metadata
from app.services.asset_metadata import CreateMetadata


def request_summary_source(request: Request) -> asset_metadata.SummarySource:
    return asset_metadata.source_for_transport(audit.request_transport(request))


async def _create_metadata_form(
    # Resolving the user first sets the transport on `request.state`.
    _user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    request: Request,
    doc_type: Annotated[str | None, Form(max_length=32)] = None,
    summary: Annotated[str | None, Form()] = None,
) -> CreateMetadata:
    return await asset_metadata.prepare_create_metadata(
        session, doc_type=doc_type, summary=summary, source=request_summary_source(request)
    )


CreateMetadataForm = Annotated[CreateMetadata, Depends(_create_metadata_form)]
