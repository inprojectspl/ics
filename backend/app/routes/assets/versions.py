"""Asset versioning: list, diff, create (multipart upload), restore. Mutations
go through `services.asset_versions.commit_new_version`."""

from __future__ import annotations

import asyncio
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import permissions
from app.auth import CurrentUser
from app.collections_io import normalize_collection_path, upload_basename
from app.config import Settings, get_settings
from app.db import get_session
from app.errors import ApiError
from app.html_bundle import (
    binary_file_detail,
    is_allowed_path,
    normalize_bundle_path,
)
from app.models import AssetVersion
from app.routes._version_param import resolve_version_or_404
from app.services import asset_versions, documents, version_diff
from app.services.versions import version_rows

router = APIRouter(prefix="/api/assets", tags=["assets"])


@router.get("/{asset_id}/versions")
async def list_versions(
    asset_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[dict]:
    """Version history, viewer level; `storage_prefix` and the author's full
    e-mail stay editor+ only."""
    asset, role = await permissions.get_viewable_asset_by_id(session, asset_id, user)
    return await version_rows(
        session,
        asset,
        privileged=not permissions.is_read_only(role),
    )


@router.get("/{asset_id}/versions/{from_v}/diff/{to_v}")
async def diff_versions(
    asset_id: UUID,
    from_v: int,
    to_v: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    path: Annotated[str | None, Query(description="Unified diff of one file (any kind)")] = None,
) -> dict:
    """Compare two versions (viewer level), one shape for every kind.

    Without `?path=`: the change list plus `from_meta`/`to_meta`, no content.
    With `?path=`: the unified diff of that file; binary gives 415 shaped as
    in `file-mcp`.
    """
    asset, role = await permissions.get_viewable_asset_by_id(session, asset_id, user)
    if from_v == to_v:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "same_version", "versions must differ")
    for v in (from_v, to_v):
        resolve_version_or_404(asset, v)

    if path is not None:
        rel = normalize_collection_path(path)
        try:
            return await version_diff.file_diff(asset, from_v, to_v, rel, settings)
        except version_diff.FileNotInEitherVersion:
            raise ApiError(
                status.HTTP_404_NOT_FOUND,
                "file_not_found",
                f"file {rel} does not exist in either compared version",
            ) from None
        except version_diff.BinaryFileDiff as e:
            raise ApiError(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                "binary_file",
                binary_file_detail(
                    e.path, e.size_bytes, "binary file; a line diff makes no sense for it"
                ),
            ) from None

    # Independent: one hits storage, the other Postgres.
    changes, rows = await asyncio.gather(
        version_diff.diff_summary(asset, from_v, to_v, settings),
        version_rows(session, asset, privileged=not permissions.is_read_only(role)),
    )
    meta = {r["version"]: r for r in rows if r["version"] in (from_v, to_v)}

    return {
        "kind": asset.kind,
        "from_version": from_v,
        "to_version": to_v,
        "from_meta": meta.get(from_v),
        "to_meta": meta.get(to_v),
        "files": version_diff.as_payload(changes),
    }


@router.post("/{asset_id}/versions", status_code=status.HTTP_201_CREATED)
async def create_version(
    asset_id: UUID,
    files: list[UploadFile],
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    paths: Annotated[list[str] | None, Form()] = None,
    change_note: Annotated[
        str | None, Form(max_length=asset_versions.CHANGE_NOTE_MAX_CHARS)
    ] = None,
) -> dict:
    """Replace asset content with a new version. The asset's kind is
    immutable, so uploads must match the existing kind's shape:
      md_single     -> exactly 1 .md file (paths optional)
      md_collection -> multiple .md, paths required (parallel to files)
      html_bundle   -> multiple files, paths required, must contain .html
      pdf_doc       -> exactly 1 .pdf file (paths ignored)
      office_doc    -> exactly 1 .docx/.odt/.doc file (paths ignored)"""
    if paths is None:
        paths = []
    asset = await permissions.get_owned_asset_by_id(session, asset_id, user)
    if len(files) > settings.max_files_per_bundle:
        raise ApiError(status.HTTP_413_CONTENT_TOO_LARGE, "bundle_too_many_files", "too many files")
    if len(files) == 0:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "no_files", "no files")

    pairs: list[tuple[UploadFile, str]]
    if asset.kind == "md_single":
        if len(files) != 1:
            raise ApiError(
                status.HTTP_400_BAD_REQUEST,
                "md_single_requires_one_file",
                "md_single expects 1 file",
            )
        f = files[0]
        if not f.filename or not f.filename.lower().endswith(".md"):
            raise ApiError(status.HTTP_400_BAD_REQUEST, "md_file_required", "expected a .md file")
        pairs = [(f, upload_basename(f.filename))]
    elif documents.is_document(asset.kind):
        doc_type = documents.document_type(asset.kind)
        if len(files) != 1:
            raise ApiError(
                status.HTTP_400_BAD_REQUEST, doc_type.wrong_file_code, "expected one document file"
            )
        pairs = [(files[0], documents.filename(asset.kind, files[0].filename))]
    else:
        if len(files) != len(paths):
            raise ApiError(
                status.HTTP_400_BAD_REQUEST, "files_paths_mismatch", "files/paths length mismatch"
            )
        if asset.kind == "md_collection":
            pairs = [
                (f, normalize_collection_path(p))
                for f, p in zip(files, paths, strict=True)
                if p.lower().endswith(".md")
            ]
            if not pairs:
                raise ApiError(
                    status.HTTP_400_BAD_REQUEST,
                    "md_files_required",
                    "no .md files in the collection",
                )
        elif asset.kind == "html_bundle":
            pairs = [
                (f, normalize_bundle_path(p))
                for f, p in zip(files, paths, strict=True)
                if is_allowed_path(normalize_bundle_path(p))
            ]
            if not pairs:
                raise ApiError(
                    status.HTTP_400_BAD_REQUEST, "no_accepted_files", "no accepted files"
                )
        else:
            raise ApiError(
                status.HTTP_400_BAD_REQUEST, "unsupported_kind", f"unsupported kind: {asset.kind}"
            )

    result = await asset_versions.commit_new_version(
        session,
        asset,
        settings,
        stage=asset_versions.write_uploads(pairs, max_bytes=settings.max_asset_bytes),
        actor=user,
        audit_action="asset_versioned",
        audit_payload=lambda nv: {
            "version": nv.version,
            "file_count": nv.file_count,
            "size_bytes": nv.size_bytes,
            "security": nv.security,
        },
        change_note=change_note,
    )
    return {
        "id": str(asset.id),
        "version": result.version,
        "entry_path": result.entry_path,
        "file_count": result.file_count,
        "size_bytes": result.size_bytes,
        "security_status": asset.security_status,
    }


@router.post("/{asset_id}/versions/{n}/restore", status_code=status.HTTP_201_CREATED)
async def restore_version(
    asset_id: UUID,
    n: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    change_note: Annotated[
        str | None, Query(max_length=asset_versions.CHANGE_NOTE_MAX_CHARS)
    ] = None,
) -> dict:
    """Roll back to an older version by copying its storage tree forward to
    version N+1. Keeps the history monotonic (no "version going backwards"
    in audit trail) and makes the rollback itself rollback-able."""
    asset = await permissions.get_owned_asset_by_id(session, asset_id, user)
    if n == asset.version:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, "version_is_current", "this version is already current"
        )
    if n < 1 or n >= asset.version:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "invalid_version", "invalid version number")

    source = (
        await session.execute(
            select(AssetVersion).where(
                AssetVersion.asset_id == asset.id,
                AssetVersion.version == n,
            )
        )
    ).scalar_one_or_none()
    if source is None:
        raise ApiError(
            status.HTTP_404_NOT_FOUND, "version_not_found", f"version {n} does not exist"
        )

    result = await asset_versions.commit_new_version(
        session,
        asset,
        settings,
        stage=asset_versions.copy_version(source.storage_prefix),
        actor=user,
        audit_action="asset_rolled_back",
        audit_payload=lambda nv: {
            "restored_from": n,
            "new_version": nv.version,
            "security": nv.security,
        },
        change_note=change_note,
    )
    return {
        "id": str(asset.id),
        "version": result.version,
        "entry_path": result.entry_path,
        "restored_from": n,
        "size_bytes": result.size_bytes,
        "security_status": asset.security_status,
    }
