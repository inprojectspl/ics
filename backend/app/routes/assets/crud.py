"""CRUD operations on a single Asset: upload markdown/collection/HTML,
rename, soft-delete, get-by-id. Pins are in `pins`.

All endpoints require a signed-in user and reach resources through
`permissions.get_owned_asset_by_id` (anti-enumeration via 404).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import delete as _delete
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, permissions, quota, search
from app.auth import CurrentUser
from app.collections_io import (
    normalize_collection_path,
    pick_entry,
    read_markdown_files,
    upload_basename,
)
from app.config import Settings, get_settings
from app.db import get_session
from app.errors import ApiError
from app.html_bundle import (
    is_allowed_path,
    normalize_bundle_path,
    pick_html_entry,
)
from app.models import Asset, AssetShare, AssetVersion, Project, ShareLink
from app.routes.assets._create_metadata import CreateMetadataForm
from app.routes.assets._helpers import UploadShareMode
from app.services import asset_security, read_size, relation_extraction
from app.services.notifications import events as notification_events
from app.services.sharing import build_share_url
from app.services.upload import ByteBudget, chunked, stage_asset_files, validate_pairs_count
from app.slug import generate_slug, generate_token
from app.storage import storage_from_url
from app.util import now as utc_now

router = APIRouter(prefix="/api/assets", tags=["assets"])


async def _upload_target_project(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    project_id: Annotated[UUID | None, Query()] = None,
) -> Project | None:
    """Resolve the optional `?project_id=` upload target, asserting the
    caller may contribute to it (owner/editor/admin), or None when the
    upload is personal. Shared by all three upload endpoints so the gate
    runs once, up front, before any storage write.
    """
    if project_id is None:
        return None
    return await permissions.assert_project_contributor(session, user, project_id)


# ---------- POST upload ----------


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_markdown(
    file: UploadFile,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    meta: CreateMetadataForm,
    share_mode: Annotated[UploadShareMode, Query()] = "org_sso",
    project: Annotated[Project | None, Depends(_upload_target_project)] = None,
) -> dict:
    if not file.filename or not file.filename.lower().endswith(".md"):
        raise ApiError(status.HTTP_400_BAD_REQUEST, "md_file_required", "only .md files accepted")
    filename = upload_basename(file.filename)

    slug = generate_slug()
    storage = storage_from_url(settings.storage_url)
    storage_key = f"assets/{slug}/v1/{filename}"
    try:
        size = await storage.put(
            storage_key, chunked(file, ByteBudget(settings.max_asset_bytes, "file too large"))
        )
    except Exception:
        await storage.delete_prefix(f"assets/{slug}")
        raise
    try:
        await quota.assert_can_grow(
            session,
            user.id,
            incoming_bytes=size,
            quota_bytes=user.storage_quota_bytes,
        )
    except quota.QuotaExceededError:
        await storage.delete_prefix(f"assets/{slug}")
        raise

    asset = Asset(
        slug=slug,
        owner_id=user.id,
        content_updated_by=user.id,
        project_id=project.id if project else None,
        kind="md_single",
        title=filename.removesuffix(".md"),
        storage_prefix=f"assets/{slug}",
        entry_path=filename,
        security_status="clean",
        size_bytes=size,
        version=1,
    )
    session.add(asset)
    meta.apply(asset)
    await session.flush()

    session.add(
        AssetVersion(
            asset_id=asset.id,
            version=1,
            storage_prefix=f"assets/{slug}/v1",
            size_bytes=size,
            created_by=user.id,
        )
    )

    sources = await read_markdown_files(asset, settings)
    await asset_security.scan_and_apply(
        asset, settings, session, actor=user, markdown_sources=sources
    )
    share = ShareLink(
        asset_id=asset.id, token=generate_token(), mode=share_mode, created_by=user.id
    )
    session.add(share)
    await search.refresh_search_content(asset, settings, sources=sources)
    await read_size.refresh_read_tokens(asset, settings, sources=sources)
    await relation_extraction.extract_from_content(session, asset, settings, user.id)
    await audit.record(
        session,
        actor=user,
        action="asset_uploaded",
        target=f"asset:{asset.id}",
        payload={"kind": "md_single", "slug": slug, "size_bytes": size, "share_mode": share_mode},
    )
    await session.commit()
    await notification_events.emit_created(asset, user)

    return {
        "id": str(asset.id),
        "slug": asset.slug,
        "title": asset.title,
        "share_url": build_share_url(settings, share.token),
    }


@router.post("/collection", status_code=status.HTTP_201_CREATED)
async def upload_collection(
    files: list[UploadFile],
    paths: Annotated[list[str], Form()],
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    meta: CreateMetadataForm,
    share_mode: Annotated[UploadShareMode, Query()] = "org_sso",
    project: Annotated[Project | None, Depends(_upload_target_project)] = None,
    entry_path: Annotated[str | None, Form()] = None,
) -> dict:
    validate_pairs_count(files, paths, settings=settings)
    md_pairs = [
        (f, normalize_collection_path(p))
        for f, p in zip(files, paths, strict=True)
        if p.lower().endswith(".md")
    ]
    if not md_pairs:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "md_files_required", "no .md files")

    # Optional explicit entry file. Validate before
    # stage_asset_files: a 400 after the write would leave orphans in storage.
    requested_entry: str | None = None
    if entry_path is not None:
        requested_entry = normalize_collection_path(entry_path)
        md_paths = {p for _, p in md_pairs}
        if requested_entry not in md_paths:
            raise ApiError(
                status.HTTP_400_BAD_REQUEST,
                "invalid_entry_path",
                f"entry_path must point to one of the uploaded .md files: {entry_path}",
            )

    staged = await stage_asset_files(
        md_pairs,
        user=user,
        settings=settings,
        session=session,
        size_limit_message="collection too large",
    )
    written_paths = [rel for rel, _ in staged.results]
    entry_path = requested_entry or pick_entry(written_paths)
    title_source = entry_path.rsplit("/", 1)[-1].removesuffix(".md")

    asset = Asset(
        slug=staged.slug,
        owner_id=user.id,
        content_updated_by=user.id,
        project_id=project.id if project else None,
        kind="md_collection",
        title=title_source,
        storage_prefix=staged.storage_prefix,
        entry_path=entry_path,
        security_status="clean",
        size_bytes=staged.total_bytes,
        version=1,
    )
    session.add(asset)
    meta.apply(asset)
    await session.flush()
    session.add(
        AssetVersion(
            asset_id=asset.id,
            version=1,
            storage_prefix=f"{staged.storage_prefix}/v1",
            size_bytes=staged.total_bytes,
            created_by=user.id,
        )
    )
    sources = await read_markdown_files(asset, settings)
    await asset_security.scan_and_apply(
        asset, settings, session, actor=user, markdown_sources=sources
    )
    session.add(
        ShareLink(
            asset_id=asset.id,
            token=generate_token(),
            mode=share_mode,
            created_by=user.id,
        )
    )
    await search.refresh_search_content(asset, settings, sources=sources)
    await read_size.refresh_read_tokens(asset, settings, sources=sources)
    await relation_extraction.extract_from_content(session, asset, settings, user.id)
    await audit.record(
        session,
        actor=user,
        action="asset_uploaded",
        target=f"asset:{asset.id}",
        payload={
            "kind": "md_collection",
            "slug": staged.slug,
            "file_count": len(written_paths),
            "size_bytes": staged.total_bytes,
            "share_mode": share_mode,
        },
    )
    await session.commit()
    await notification_events.emit_created(asset, user)
    return {
        "id": str(asset.id),
        "slug": asset.slug,
        "title": asset.title,
        "kind": asset.kind,
        "entry_path": asset.entry_path,
        "file_count": len(written_paths),
    }


@router.post("/html", status_code=status.HTTP_201_CREATED)
async def upload_html_bundle(
    files: list[UploadFile],
    paths: Annotated[list[str], Form()],
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    meta: CreateMetadataForm,
    share_mode: Annotated[UploadShareMode, Query()] = "org_sso",
    project: Annotated[Project | None, Depends(_upload_target_project)] = None,
) -> dict:
    validate_pairs_count(files, paths, settings=settings)
    pairs = [
        (file, normalize_bundle_path(p))
        for file, p in zip(files, paths, strict=True)
        if is_allowed_path(normalize_bundle_path(p))
    ]
    if not pairs:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "no_accepted_files", "no accepted files")

    entry_path = pick_html_entry([rel for _, rel in pairs])
    staged = await stage_asset_files(
        pairs,
        user=user,
        settings=settings,
        session=session,
        size_limit_message="bundle too large",
        bundle_max_bytes=user.bundle_max_bytes,
    )
    title_source = entry_path.rsplit("/", 1)[-1].removesuffix(".html").removesuffix(".htm")

    asset = Asset(
        slug=staged.slug,
        owner_id=user.id,
        content_updated_by=user.id,
        project_id=project.id if project else None,
        kind="html_bundle",
        title=title_source or "html",
        storage_prefix=staged.storage_prefix,
        entry_path=entry_path,
        security_status="clean",
        size_bytes=staged.total_bytes,
        version=1,
    )
    session.add(asset)
    meta.apply(asset)
    await session.flush()
    session.add(
        AssetVersion(
            asset_id=asset.id,
            version=1,
            storage_prefix=f"{staged.storage_prefix}/v1",
            size_bytes=staged.total_bytes,
            created_by=user.id,
        )
    )
    scan_summary = await asset_security.scan_and_apply(asset, settings, session, actor=user)
    await read_size.refresh_read_tokens(asset, settings)
    await relation_extraction.extract_from_content(session, asset, settings, user.id)
    # Critical bundle: skip the default share; the owner must wait for admin
    # approval before any link is created.
    if not asset_security.publication_blocked(asset):
        session.add(
            ShareLink(
                asset_id=asset.id,
                token=generate_token(),
                mode=share_mode,
                created_by=user.id,
            )
        )
    await audit.record(
        session,
        actor=user,
        action="asset_uploaded",
        target=f"asset:{asset.id}",
        payload={
            "kind": "html_bundle",
            "slug": staged.slug,
            "file_count": len(staged.results),
            "size_bytes": staged.total_bytes,
            "entry_path": entry_path,
            "security": scan_summary,
            "share_mode": (None if asset_security.publication_blocked(asset) else share_mode),
        },
    )
    await session.commit()
    await notification_events.emit_created(asset, user)
    return {
        "id": str(asset.id),
        "slug": asset.slug,
        "title": asset.title,
        "kind": asset.kind,
        "entry_path": entry_path,
        "file_count": len(staged.results),
        "security_status": asset.security_status,
    }


# ---------- PATCH / DELETE / GET single asset ----------


class PatchAssetIn(BaseModel):
    title: str = Field(min_length=1, max_length=500)


@router.patch("/{asset_id}")
async def patch_asset(
    asset_id: UUID,
    body: PatchAssetIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    asset = await permissions.get_owned_asset_by_id(session, asset_id, user)
    old_title = asset.title
    asset.title = body.title.strip()
    await audit.record(
        session,
        actor=user,
        action="asset_renamed",
        target=f"asset:{asset.id}",
        payload={"from": old_title, "to": asset.title},
    )
    await session.commit()
    return {"id": str(asset.id), "title": asset.title}


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asset(
    asset_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    asset = await session.get(Asset, asset_id)
    if asset is None or asset.deleted_at is not None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "asset_not_found", "asset not found")
    role = await permissions.effective_role(session, user, asset)
    # Tighter than the default editor gate: only the file's owner or the
    # project's owner (or sys-admin) can soft-delete. Editors collaborate
    # on content; removing the file is a structural change.
    if role not in ("owner_file", "project_owner"):
        raise ApiError(status.HTTP_404_NOT_FOUND, "asset_not_found", "asset not found")

    now = utc_now()
    asset.deleted_at = now
    # Soft cascade: keeps historical share IDs in the audit trail.
    await session.execute(
        update(ShareLink)
        .where(ShareLink.asset_id == asset.id, ShareLink.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    # Per-user shares get dropped: restoring on undelete would re-create
    # "zombie" grants the original sharer might no longer want.
    await session.execute(_delete(AssetShare).where(AssetShare.asset_id == asset.id))
    await audit.record(
        session,
        actor=user,
        action="asset_deleted",
        target=f"asset:{asset.id}",
        payload={"slug": asset.slug, "kind": asset.kind},
    )
    await session.commit()
    await notification_events.emit_deleted(asset, user)


@router.get("/{asset_id}")
async def get_asset(
    asset_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Return the asset if the user has at least `editor` on it (owner,
    project member with editor+, asset-share editor, admin). Everyone else
    gets 404, per the anti-enumeration policy of the central `permissions`.
    """
    asset = await permissions.get_owned_asset_by_id(session, asset_id, user)
    return {
        "id": str(asset.id),
        "slug": asset.slug,
        "kind": asset.kind,
        "title": asset.title,
        "version": asset.version,
        "size_bytes": asset.size_bytes,
        "created_at": asset.created_at.isoformat(),
    }
