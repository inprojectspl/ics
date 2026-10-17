"""Creating a new asset version: the only code that bumps `asset.version`.

`commit_new_version` locks the asset row so concurrent writers cannot both
claim v{n+1}, and a failure before the commit removes the new tree while the
lock is still held, so the current version stays intact.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, quota, search
from app.bundle_extract import extract_to_storage
from app.bundle_scan import prompt_injection
from app.collections_io import derive_entry_path, read_markdown_files
from app.config import Settings
from app.domain_errors import InvalidInputError, NotFoundError
from app.models import Asset, AssetVersion, User
from app.services import asset_security, documents, ocr, read_size, relation_extraction
from app.services.notifications import events as notification_events
from app.services.upload import ByteBudget, ReadableFile, one_chunk, put_all
from app.storage import Storage, storage_from_url
from app.util import now as utc_now

# Author's note on a version (the equivalent of a commit message).
CHANGE_NOTE_MAX_CHARS = 1000


@dataclass(frozen=True)
class VersionDraft:
    """What a stage gets: the locked asset (still at the current version) and
    the storage holding its current tree and the empty tree it must fill."""

    asset: Asset
    storage: Storage

    @property
    def version(self) -> int:
        return self.asset.version + 1

    @property
    def base_prefix(self) -> str:
        return f"{self.asset.storage_prefix}/v{self.asset.version}"

    @property
    def prefix(self) -> str:
        return f"{self.asset.storage_prefix}/v{self.version}"


@dataclass(frozen=True)
class StagedTree:
    """What a stage wrote. `size_bytes` of `None` keeps the recorded size
    (legacy rows without one); `entry_path` of `None` keeps the current entry."""

    size_bytes: int | None
    entry_path: str | None = None
    file_count: int | None = None


@dataclass(frozen=True)
class NewVersion:
    version: int
    size_bytes: int | None
    entry_path: str | None
    file_count: int | None
    security: dict | None


Stage = Callable[[VersionDraft], Awaitable[StagedTree]]
AuditPayload = Callable[[NewVersion], dict[str, Any]]


async def commit_new_version(
    session: AsyncSession,
    asset: Asset,
    settings: Settings,
    *,
    stage: Stage,
    actor: User | str,
    audit_action: str,
    audit_payload: AuditPayload,
    created_by: UUID | None = None,
    change_note: str | None = None,
) -> NewVersion:
    """Write a new version of `asset` with `stage` and commit the session.

    `created_by` defaults to the acting user. The commit also saves whatever
    else the caller changed in the session (the CI sync relies on it).
    """
    await session.refresh(asset, with_for_update=True)
    user = actor if isinstance(actor, User) else None
    if created_by is None and user is not None:
        created_by = user.id
    draft = VersionDraft(asset=asset, storage=storage_from_url(settings.storage_url))
    version, prefix = draft.version, draft.prefix
    await draft.storage.delete_prefix(prefix)
    try:
        staged = await stage(draft)
        await _enforce_limits(session, asset, staged, settings)
        converted = None
        ocr_run = None
        if documents.is_document(asset.kind):
            converted = await documents.ingest(
                draft.storage,
                kind=asset.kind,
                storage_prefix=asset.storage_prefix,
                version=version,
                entry_path=staged.entry_path or asset.entry_path or "",
                settings=settings,
            )

        asset.version = version
        asset.content_updated_at = utc_now()
        asset.content_updated_by = created_by
        # The cached outline describes the previous version; the sweeper
        # only rebuilds rows that are not `fresh`.
        asset.outline_status = "stale"
        if staged.size_bytes is not None:
            asset.size_bytes = staged.size_bytes
        if staged.entry_path is not None:
            asset.entry_path = staged.entry_path
        session.add(
            AssetVersion(
                asset_id=asset.id,
                version=version,
                storage_prefix=prefix,
                size_bytes=asset.size_bytes,
                created_by=created_by,
                change_note=(change_note or "").strip() or None,
            )
        )
        # Markdown is read once for the prompt-injection scan and the search blob.
        sources = (
            await read_markdown_files(asset, settings)
            if prompt_injection.is_markdown_kind(asset.kind)
            else None
        )
        security = await asset_security.scan_and_apply(
            asset, settings, session, actor=user, markdown_sources=sources
        )
        if converted is not None:
            # The text is at hand; re-reading it would cost a derived-file
            # round trip for nothing.
            asset.search_content = documents.search_content_of(asset.kind, converted)
            ocr_run = ocr.queue_after_write(
                session, asset, version, converted, settings, requested_by=created_by
            )
        else:
            await search.refresh_search_content(asset, settings, sources=sources)
        await read_size.refresh_read_tokens(asset, settings, sources=sources, converted=converted)
        await relation_extraction.extract_from_content(
            session, asset, settings, user.id if user else created_by, converted=converted
        )
        result = NewVersion(
            version=version,
            size_bytes=asset.size_bytes,
            entry_path=asset.entry_path,
            file_count=staged.file_count,
            security=security,
        )
        await audit.record(
            session,
            actor=actor,
            action=audit_action,
            target=f"asset:{asset.id}",
            payload=audit_payload(result),
        )
    except Exception:
        await draft.storage.delete_prefix(prefix)
        if documents.is_document(asset.kind):
            await draft.storage.delete_prefix(
                documents.derived_prefix(asset.storage_prefix, version)
            )
        raise
    # No cleanup after a failed commit: the row lock is gone by then and a
    # concurrent writer may already be filling the same prefix. The next
    # writer clears the prefix before staging.
    await session.commit()
    await ocr.enqueue(ocr_run, settings)
    # A CI sync has no user actor: its versions notify everyone watching.
    await notification_events.emit_updated(asset, version, user, settings)
    return result


async def _enforce_limits(
    session: AsyncSession, asset: Asset, staged: StagedTree, settings: Settings
) -> None:
    """The owner pays for the asset, whoever edits it, so both limits are the
    owner's. Only growth is checked: shrinking an asset is always allowed,
    even for an owner who is already over quota."""
    if staged.size_bytes is None:
        return
    owner = await session.get(User, asset.owner_id)
    if owner is None:
        return
    if documents.is_document(asset.kind):
        documents.assert_size(asset.kind, staged.size_bytes, settings)
    if asset.kind == "html_bundle":
        quota.assert_bundle_fits(
            total_bytes=staged.size_bytes, bundle_max_bytes=owner.bundle_max_bytes
        )
    growth = staged.size_bytes - (asset.size_bytes or 0)
    if growth > 0:
        await quota.assert_can_grow(
            session, owner.id, incoming_bytes=growth, quota_bytes=owner.storage_quota_bytes
        )


# Stages


def edit_files(
    *,
    put: Mapping[str, bytes] | None = None,
    delete: Collection[str] = (),
    size_delta: int | None = None,
    entry_path: str | None = None,
    carry_over: bool = True,
) -> Stage:
    """Per-file edit: carry the current tree over, then delete and write the
    given paths. The new size is `current + size_delta` (`None` keeps it), so
    the tree is not re-listed. `carry_over=False` skips the copy when the write
    replaces the whole tree."""

    async def _stage(draft: VersionDraft) -> StagedTree:
        if carry_over:
            await draft.storage.copy_prefix(draft.base_prefix, draft.prefix)
        for rel in delete:
            await draft.storage.delete(f"{draft.prefix}/{rel}")
        for rel, data in (put or {}).items():
            await draft.storage.put(f"{draft.prefix}/{rel}", one_chunk(data))
        size = None
        if size_delta is not None:
            size = max(0, (draft.asset.size_bytes or 0) + size_delta)
        return StagedTree(size_bytes=size, entry_path=entry_path)

    return _stage


def write_uploads(pairs: Sequence[tuple[ReadableFile, str]], *, max_bytes: int) -> Stage:
    """Full replacement from uploaded `(file, rel_path)` pairs."""

    async def _stage(draft: VersionDraft) -> StagedTree:
        results = await put_all(
            draft.storage, draft.prefix, pairs, ByteBudget(max_bytes, "too large")
        )
        written = [rel for rel, _ in results]
        return StagedTree(
            size_bytes=sum(size for _, size in results),
            entry_path=derive_entry_path(draft.asset.kind, written),
            file_count=len(written),
        )

    return _stage


def copy_version(source_prefix: str) -> Stage:
    """Restore: copy an older version's tree forward as the new version."""

    async def _stage(draft: VersionDraft) -> StagedTree:
        try:
            total = await draft.storage.copy_prefix(source_prefix, draft.prefix)
        except FileNotFoundError:
            raise NotFoundError("version_files_missing", "version files are gone") from None
        keys = await draft.storage.list_prefix(f"{draft.prefix}/")
        rel_paths = [k.removeprefix(f"{draft.prefix}/") for k in keys]
        return StagedTree(
            size_bytes=total,
            entry_path=derive_entry_path(draft.asset.kind, rel_paths),
            file_count=len(rel_paths),
        )

    return _stage


def extract_bundle(bundle_bytes: bytes, settings: Settings) -> Stage:
    """CI sync: unpack a signed tar.gz as the new version. The content must
    match the asset's kind, so a vault cannot be replaced with an HTML bundle."""

    async def _stage(draft: VersionDraft) -> StagedTree:
        written, total = await extract_to_storage(
            bundle_bytes=bundle_bytes,
            storage=draft.storage,
            dest_prefix=draft.prefix,
            max_files=settings.max_files_per_bundle,
            max_total_bytes=settings.max_asset_bytes,
        )
        if not written:
            raise InvalidInputError("no_files", "the bundle contains no files")
        return StagedTree(
            size_bytes=total,
            entry_path=derive_entry_path(draft.asset.kind, written),
            file_count=len(written),
        )

    return _stage
