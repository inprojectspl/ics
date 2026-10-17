"""Signed sync from GitLab CI: verify the push, then write a new version."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request, UploadFile, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, ratelimit, signing
from app.config import Settings, get_settings
from app.db import get_session
from app.errors import ApiError
from app.models import Asset, GitLabBinding
from app.redis_client import get_redis
from app.services import asset_versions, notifications
from app.util import ip_hash
from app.util import now as utc_now

from ._models import Manifest
from ._router import router


@router.post("/{binding_id}/sync", status_code=status.HTTP_201_CREATED)
async def sync_binding(
    request: Request,
    binding_id: UUID,
    manifest: UploadFile,
    signature: UploadFile,
    bundle: UploadFile,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    """Verify a signed push from GitLab CI and create a new asset version.

    Auth: signature must match the binding's stored public key.
    The endpoint is not cookie/session-authenticated: anybody can POST,
    but only payloads signed by the matching private key are accepted.
    """
    redis = get_redis()
    if not await ratelimit.check_and_incr(redis, ratelimit.BINDING_SYNC, ip_hash(request)):
        raise ApiError(status.HTTP_429_TOO_MANY_REQUESTS, "rate_limited", "rate_limited")

    binding = await session.get(GitLabBinding, binding_id)
    if binding is None:
        await audit.record(
            session,
            actor="anonymous",
            action="binding_sync_failed",
            target=f"binding:{binding_id}",
            payload={"reason": "unknown_binding"},
        )
        await session.commit()
        raise ApiError(status.HTTP_404_NOT_FOUND, "binding_not_found", "binding not found")

    # Verify signature on manifest before reading the (potentially 100 MB)
    # bundle. Forged requests pay only manifest+signature read costs.
    manifest_bytes = await manifest.read()
    signature_b64 = (await signature.read()).decode("ascii", errors="replace").strip()
    # Ed25519 verify + PEM parse cost ~10-30 ms CPU; offload so the event loop is not blocked.
    if not await asyncio.to_thread(
        signing.verify, manifest_bytes, signature_b64, binding.public_key
    ):
        await audit.record(
            session,
            actor="anonymous",
            action="binding_sync_failed",
            target=f"binding:{binding.id}",
            payload={"reason": "bad_signature"},
        )
        await session.commit()
        raise ApiError(status.HTTP_403_FORBIDDEN, "bad_signature", "bad signature")

    try:
        m = Manifest.model_validate_json(manifest_bytes)
    except ValidationError as e:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, "manifest_invalid", f"manifest invalid: {e}"
        ) from e

    if m.binding_id != binding.id:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "manifest_mismatch", "binding_id mismatch")

    # Normalize manifest timestamp to aware UTC for comparison with the
    # column (TIMESTAMPTZ).
    manifest_ts = m.commit_timestamp
    if manifest_ts.tzinfo is None:
        manifest_ts = manifest_ts.replace(tzinfo=UTC)

    # Allow up to 5 min forward clock skew on CI side.
    if manifest_ts > utc_now() + timedelta(minutes=5):
        raise ApiError(status.HTTP_400_BAD_REQUEST, "commit_from_future", "commit from the future")

    # Replay check needs only the manifest, so a replayed push is refused
    # before the bundle is read or hashed.
    if binding.last_sync_timestamp is not None and manifest_ts <= binding.last_sync_timestamp:
        raise ApiError(status.HTTP_409_CONFLICT, "replay_rejected", "replay or out-of-order push")

    bundle_bytes = await bundle.read()
    # Hashing 100 MB costs a few hundred ms of CPU, so it is offloaded too.
    digest = await asyncio.to_thread(lambda: hashlib.sha256(bundle_bytes).hexdigest())
    if digest != m.bundle_sha256:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "bundle_hash_mismatch", "bundle hash mismatch")

    asset = await session.get(Asset, binding.asset_id)
    if asset is None or asset.deleted_at is not None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "asset_not_found", "asset not found")

    # The check above ran before the bundle was read; a newer push may have
    # landed meanwhile. Under the row lock, held until the version commits,
    # an older push cannot overwrite it.
    await session.refresh(binding, with_for_update=True)
    if binding.last_sync_timestamp is not None and manifest_ts <= binding.last_sync_timestamp:
        raise ApiError(status.HTTP_409_CONFLICT, "replay_rejected", "replay or out-of-order push")

    binding.last_sync_at = utc_now()
    binding.last_sync_commit_sha = m.commit_sha
    binding.last_sync_timestamp = manifest_ts
    # The version counts against the asset owner's quota: the binding may
    # have been created by someone who has since left.
    result = await asset_versions.commit_new_version(
        session,
        asset,
        settings,
        stage=asset_versions.extract_bundle(bundle_bytes, settings),
        actor=f"binding:{binding.id}",
        created_by=binding.created_by,
        audit_action="binding_synced",
        audit_payload=lambda nv: {
            "commit_sha": m.commit_sha,
            "commit_timestamp": manifest_ts.isoformat(),
            "version": nv.version,
            "file_count": nv.file_count,
            "size_bytes": nv.size_bytes,
            "security": nv.security,
        },
    )

    # Notify after commit; the dispatcher decides whether to send
    # (no provider / unknown provider / no share link: silent skip).
    # The provider timeout (~3 s) is the only delay the CI runner sees.
    await notifications.dispatch_sync_notification(
        binding=binding,
        asset=asset,
        new_version=result.version,
        file_count=result.file_count or 0,
        commit_sha=m.commit_sha,
        security_status=(result.security or {}).get("status"),
        session=session,
        settings=settings,
    )

    return {
        "version": result.version,
        "entry_path": result.entry_path,
        "file_count": result.file_count,
        "size_bytes": result.size_bytes,
        "commit_sha": m.commit_sha,
        "security_status": asset.security_status,
    }
