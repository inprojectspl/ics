"""Move or rename a file inside an md_collection.

Registers on the `content` router; split out to keep `content.py` under
the file size budget.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app import permissions
from app.auth import CurrentUser
from app.collections_io import list_version_files, normalize_collection_path, read_text
from app.config import Settings, get_settings
from app.db import get_session
from app.errors import ApiError
from app.routes.assets.content import _require_collection, router
from app.services import asset_versions


class MoveFileIn(BaseModel):
    from_path: str = Field(min_length=1, max_length=500)
    to_path: str = Field(min_length=1, max_length=500)
    change_note: str | None = Field(default=None, max_length=asset_versions.CHANGE_NOTE_MAX_CHARS)


@router.patch("/{asset_id}/files/move")
async def move_file_in_collection(
    asset_id: UUID,
    body: MoveFileIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    """Move a file in a vault from `from_path` to `to_path` (full path,
    including the new filename; the caller decides if it's a folder change,
    a rename, or both). Copies the version tree, deletes the source,
    writes the destination. Total size unchanged."""
    asset = await permissions.get_owned_asset_by_id(session, asset_id, user)
    _require_collection(asset, "moving files is only available for Markdown collections")

    from_rel = normalize_collection_path(body.from_path)
    to_rel = normalize_collection_path(body.to_path)
    if from_rel == to_rel:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "same_path",
            "source and destination paths are identical",
        )
    if not from_rel.lower().endswith(".md") or not to_rel.lower().endswith(".md"):
        raise ApiError(status.HTTP_400_BAD_REQUEST, "md_file_required", "only .md files")

    try:
        moved_text = await read_text(asset, from_rel, settings)
    except FileNotFoundError:
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            "file_not_found",
            f"file {from_rel} does not exist in the current version",
        ) from None

    current_files = await list_version_files(asset, asset.version, settings)
    if to_rel in current_files:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "file_exists",
            f"file {to_rel} already exists; choose another name",
        )

    # Total bytes unchanged: same content, just renamed/relocated.
    result = await asset_versions.commit_new_version(
        session,
        asset,
        settings,
        stage=asset_versions.edit_files(
            put={to_rel: moved_text.encode("utf-8")},
            delete=[from_rel],
            entry_path=to_rel if from_rel == asset.entry_path else None,
        ),
        actor=user,
        audit_action="vault_file_moved",
        audit_payload=lambda nv: {"version": nv.version, "from": from_rel, "to": to_rel},
        change_note=body.change_note,
    )
    return {
        "id": str(asset.id),
        "version": result.version,
        "from_path": from_rel,
        "to_path": to_rel,
        "entry_path": result.entry_path,
    }
