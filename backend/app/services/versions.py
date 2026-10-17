"""Version history and version-number validation for read-only preview
(ADR-0004), shared by the owner's version list, history behind a share token
and archived version preview. Nothing here bumps `asset.version`; an
out-of-range version raises `VersionNotFound`, which routes map to 404.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collections_io import derive_entry_path, list_version_files
from app.config import Settings
from app.models import Asset, AssetVersion, User


class VersionNotFound(LookupError):
    """The requested asset version does not exist (outside 1..asset.version)."""


def resolve_preview_version(asset: Asset, version: int | None) -> int:
    """Version number to read: `None` means current. The single range
    validation point for every surface with `?version=`."""
    if version is None:
        return asset.version
    if version < 1 or version > asset.version:
        raise VersionNotFound(f"version {version} does not exist")
    return version


def author_label(display_name: str | None, email: str | None) -> str | None:
    """Version author label that does not reveal the e-mail domain.

    A `public` link can end up on the internet, and the update history should
    show who changed the file, not the address at which they can be reached.
    `display_name` if set, otherwise the local part of the e-mail.
    """
    if display_name:
        return display_name
    if email:
        return email.split("@", 1)[0]
    return None


async def version_rows(
    session: AsyncSession, asset: Asset, *, privileged: bool = False
) -> list[dict]:
    """Version history, newest first. `privileged` (editor+) reveals the
    storage path and the author's full e-mail; by default a guest gets only
    the masked author label."""
    rows = (
        await session.execute(
            select(
                AssetVersion.version,
                AssetVersion.size_bytes,
                AssetVersion.storage_prefix,
                AssetVersion.created_at,
                AssetVersion.created_by,
                AssetVersion.change_note,
                User.display_name,
                User.email,
            )
            .outerjoin(User, User.id == AssetVersion.created_by)
            .where(AssetVersion.asset_id == asset.id)
            .order_by(AssetVersion.version.desc())
        )
    ).all()

    return [
        {
            "version": version,
            "size_bytes": size_bytes,
            "storage_prefix": storage_prefix if privileged else None,
            "created_at": created_at.isoformat(),
            "created_by": str(created_by) if created_by else None,
            "author": author_label(display_name, email),
            "author_email": email if privileged else None,
            "is_current": version == asset.version,
            "change_note": change_note,
        }
        for (
            version,
            size_bytes,
            storage_prefix,
            created_at,
            created_by,
            change_note,
            display_name,
            email,
        ) in rows
    ]


async def version_created_at(session: AsyncSession, asset: Asset, version: int) -> datetime | None:
    """Creation date of a given version; the "outdated version" banner shows
    it next to the number. `None` when the history row does not exist (assets
    from before versioning have v1 without an `AssetVersion` row)."""
    return (
        await session.execute(
            select(AssetVersion.created_at).where(
                AssetVersion.asset_id == asset.id,
                AssetVersion.version == version,
            )
        )
    ).scalar_one_or_none()


def entry_from_paths(asset: Asset, version: int, paths: list[str]) -> str | None:
    """Entry file of a version when the listing is already at hand (no I/O),
    None when it has no files. Only the current version may use
    `asset.entry_path`; an archived one may not contain that file."""
    if version == asset.version:
        return asset.entry_path
    return derive_entry_path(asset.kind, paths) if paths else None


async def entry_path_at_version(asset: Asset, version: int, settings: Settings) -> str | None:
    """Like `entry_from_paths`, but fetches the listing itself, for call sites
    that do not need the file list. Does not list for the current version (the
    answer is in the asset row)."""
    if version == asset.version:
        return asset.entry_path
    return entry_from_paths(asset, version, await list_version_files(asset, version, settings))
