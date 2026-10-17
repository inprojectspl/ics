"""Per-file editing of Markdown content (move is in `file_move`). Every
operation creates a new version; html_bundle has no per-file edit semantics."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app import permissions
from app.auth import CurrentUser
from app.collections_io import (
    list_md_paths,
    list_version_files,
    normalize_collection_path,
    pick_entry,
    read_text,
)
from app.config import Settings, get_settings
from app.db import get_session
from app.errors import ApiError
from app.models import Asset
from app.routes.assets._helpers import entry_or_404
from app.services import asset_versions, documents

router = APIRouter(prefix="/api/assets", tags=["assets"])


def _require_collection(asset: Asset, detail: str) -> None:
    if asset.kind != "md_collection":
        raise ApiError(status.HTTP_400_BAD_REQUEST, "collection_only", detail)


class EditContentIn(BaseModel):
    content: str = Field(max_length=10_000_000)  # 10 MB hard cap; quota does the soft one
    path: str | None = Field(default=None, max_length=500)
    change_note: str | None = Field(default=None, max_length=asset_versions.CHANGE_NOTE_MAX_CHARS)


class NewEmptyFileIn(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    change_note: str | None = Field(default=None, max_length=asset_versions.CHANGE_NOTE_MAX_CHARS)


@router.put("/{asset_id}/content", status_code=status.HTTP_201_CREATED)
async def edit_content(
    asset_id: UUID,
    body: EditContentIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    """Inline edit: rewrite one .md file's content, creating a new version."""
    asset = await permissions.get_owned_asset_by_id(session, asset_id, user)
    if asset.kind == "html_bundle":
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "html_bundle_not_editable",
            "HTML bundles do not support inline editing",
        )
    if documents.is_document(asset.kind):
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            documents.document_type(asset.kind).not_editable_code,
            "documents do not support inline editing; upload a new version",
        )

    if asset.kind == "md_single":
        rel = body.path or entry_or_404(asset)
        if rel != asset.entry_path:
            raise ApiError(
                status.HTTP_400_BAD_REQUEST, "md_single_one_file", "md_single has only one file"
            )
        old_content: str | None = None
    else:  # md_collection
        if not body.path:
            raise ApiError(
                status.HTTP_400_BAD_REQUEST,
                "path_required",
                "md_collection needs `path` to edit a specific file",
            )
        rel = normalize_collection_path(body.path)
        if not rel.lower().endswith(".md"):
            raise ApiError(
                status.HTTP_400_BAD_REQUEST, "md_file_required", "only .md files can be edited"
            )
        # The read doubles as the existence check; the previous content is
        # needed a few lines below anyway.
        try:
            old_content = await read_text(asset, rel, settings)
        except FileNotFoundError:
            raise ApiError(
                status.HTTP_404_NOT_FOUND,
                "file_not_found",
                f"file {rel} does not exist in the current version",
            ) from None

    new_content = body.content
    if old_content is None:
        old_content = await read_text(asset, rel, settings)
    if old_content == new_content:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "no_changes", "content has not changed")

    new_bytes = new_content.encode("utf-8")
    old_bytes_count = len(old_content.encode("utf-8"))
    result = await asset_versions.commit_new_version(
        session,
        asset,
        settings,
        stage=asset_versions.edit_files(
            put={rel: new_bytes},
            size_delta=len(new_bytes) - old_bytes_count,
            # md_single is this one file, so there is nothing to carry over.
            carry_over=asset.kind == "md_collection",
        ),
        actor=user,
        audit_action="asset_edited",
        audit_payload=lambda nv: {
            "version": nv.version,
            "path": rel,
            "old_bytes": old_bytes_count,
            "new_bytes": len(new_bytes),
        },
        change_note=body.change_note,
    )
    return {
        "id": str(asset.id),
        "version": result.version,
        "path": rel,
        "size_bytes": result.size_bytes,
    }


@router.delete("/{asset_id}/files")
async def delete_file_in_collection(
    asset_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    path: Annotated[str, Query(max_length=500)],
    change_note: Annotated[
        str | None, Query(max_length=asset_versions.CHANGE_NOTE_MAX_CHARS)
    ] = None,
) -> dict:
    """Remove a single .md file from a vault, bumping the asset version.

    Refuses to delete the last file (the asset would become an empty
    collection, which the rest of the system doesn't model). If the
    deleted file was the `entry_path`, picks a new entry deterministically
    (readme/index/alphabetical first)."""
    asset = await permissions.get_owned_asset_by_id(session, asset_id, user)
    _require_collection(asset, "deleting single files is only available for md_collection")
    rel = normalize_collection_path(path)
    if not rel.lower().endswith(".md"):
        raise ApiError(status.HTTP_400_BAD_REQUEST, "md_file_required", "only .md files")
    # The read doubles as the existence check and gives the size delta.
    try:
        old_text = await read_text(asset, rel, settings)
    except FileNotFoundError:
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            "file_not_found",
            f"file {rel} does not exist in the current version",
        ) from None
    removed_bytes = len(old_text.encode("utf-8"))

    current_md = await list_md_paths(asset, settings)
    if len(current_md) <= 1:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "last_file",
            "cannot delete the last file of a vault; delete the whole document instead",
        )

    new_entry = None
    if rel == asset.entry_path:
        new_entry = pick_entry([p for p in current_md if p != rel])
    result = await asset_versions.commit_new_version(
        session,
        asset,
        settings,
        stage=asset_versions.edit_files(
            delete=[rel], size_delta=-removed_bytes, entry_path=new_entry
        ),
        actor=user,
        audit_action="vault_file_deleted",
        audit_payload=lambda nv: {
            "version": nv.version,
            "path": rel,
            "new_entry": nv.entry_path,
        },
        change_note=change_note,
    )
    return {
        "id": str(asset.id),
        "version": result.version,
        "deleted_path": rel,
        "entry_path": result.entry_path,
        "size_bytes": result.size_bytes,
    }


@router.post("/{asset_id}/files", status_code=status.HTTP_201_CREATED)
async def add_file_to_collection(
    asset_id: UUID,
    file: UploadFile,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    path: Annotated[str | None, Form(max_length=500)] = None,
    change_note: Annotated[
        str | None, Form(max_length=asset_versions.CHANGE_NOTE_MAX_CHARS)
    ] = None,
) -> dict:
    """Add a new .md file to an existing vault, bumping the asset version.

    `path` is the relative location inside the vault. If omitted, falls
    back to the uploaded filename (top-level). Refuses to overwrite
    existing files (use PUT /content for that)."""
    asset = await permissions.get_owned_asset_by_id(session, asset_id, user)
    _require_collection(asset, "adding single files is only available for md_collection")
    raw_path = (path or file.filename or "").strip()
    if not raw_path:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "path_required", "no path or file name given")
    rel = normalize_collection_path(raw_path)
    if not rel.lower().endswith(".md"):
        raise ApiError(status.HTTP_400_BAD_REQUEST, "md_file_required", "only .md files")

    current_files = await list_version_files(asset, asset.version, settings)
    if rel in current_files:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "file_exists",
            f"file {rel} already exists; edit it instead of adding",
        )

    content = await file.read()
    if len(content) > 10_000_000:
        raise ApiError(
            status.HTTP_413_CONTENT_TOO_LARGE,
            "upload_too_large",
            "file too large (max 10 MB)",
        )

    result = await asset_versions.commit_new_version(
        session,
        asset,
        settings,
        stage=asset_versions.edit_files(put={rel: content}, size_delta=len(content)),
        actor=user,
        audit_action="vault_file_added",
        audit_payload=lambda nv: {"version": nv.version, "path": rel, "bytes": len(content)},
        change_note=change_note,
    )
    return {
        "id": str(asset.id),
        "version": result.version,
        "added_path": rel,
        "size_bytes": result.size_bytes,
    }


@router.post("/{asset_id}/files/empty", status_code=status.HTTP_201_CREATED)
async def create_empty_file_in_collection(
    asset_id: UUID,
    body: NewEmptyFileIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    """Create an empty .md file in a vault at `path`. Same version-bump
    + audit ceremony as `add_file_to_collection`, but no multipart body:
    the UI opens the inline editor on the new file straight away."""
    asset = await permissions.get_owned_asset_by_id(session, asset_id, user)
    _require_collection(asset, "creating empty files is only available for Markdown collections")
    rel = normalize_collection_path(body.path)
    if not rel.lower().endswith(".md"):
        raise ApiError(status.HTTP_400_BAD_REQUEST, "md_file_required", "only .md files")

    current_files = await list_version_files(asset, asset.version, settings)
    if rel in current_files:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "file_exists",
            f"file {rel} already exists; edit it instead of creating",
        )

    result = await asset_versions.commit_new_version(
        session,
        asset,
        settings,
        stage=asset_versions.edit_files(put={rel: b""}),
        actor=user,
        audit_action="vault_file_added",
        audit_payload=lambda nv: {"version": nv.version, "path": rel, "bytes": 0, "empty": True},
        change_note=body.change_note,
    )
    return {
        "id": str(asset.id),
        "version": result.version,
        "added_path": rel,
        "size_bytes": result.size_bytes,
    }
