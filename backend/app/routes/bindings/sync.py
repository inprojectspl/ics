"""Signed sync from GitLab CI: verify the push, then write a new version."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
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
from app.services import asset_versions, binding_publications, notifications, publications
from app.util import ip_hash
from app.util import now as utc_now

from ._models import Manifest
from ._router import router


def _assert_legacy_order(binding: GitLabBinding, timestamp: datetime) -> None:
    if binding.last_release_generation is not None:
        raise ApiError(409, "release_required", "binding requires signed release identity")
    if binding.last_sync_timestamp is not None and timestamp <= binding.last_sync_timestamp:
        raise ApiError(409, "replay_rejected", "replay or out-of-order push")


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
    verified_key = binding.public_key
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

    # Keep the legacy cheap rejection. Signed releases must validate the
    # actual bundle before they may recover an already committed result.
    if m.release_id is None:
        _assert_legacy_order(binding, manifest_ts)

    bundle_bytes = await bundle.read()
    # Hashing 100 MB costs a few hundred ms of CPU, so it is offloaded too.
    digest = await asyncio.to_thread(lambda: hashlib.sha256(bundle_bytes).hexdigest())
    if digest != m.bundle_sha256:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "bundle_hash_mismatch", "bundle hash mismatch")

    # Recheck the principal and order after upload and lock acquisition. The
    # same binding lock covers receipt lookup and the version's commit.
    binding = await session.get(
        GitLabBinding, binding_id, with_for_update=True, populate_existing=True
    )
    if binding is None:
        raise ApiError(404, "binding_not_found", "binding not found")
    if binding.public_key != verified_key and not await asyncio.to_thread(
        signing.verify, manifest_bytes, signature_b64, binding.public_key
    ):
        raise ApiError(403, "bad_signature", "binding signing key changed")
    asset = await session.get(Asset, binding.asset_id, with_for_update=True, populate_existing=True)
    if asset is None or asset.deleted_at is not None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "asset_not_found", "asset not found")

    publication = None
    if m.release_id is None:
        _assert_legacy_order(binding, manifest_ts)
    else:
        assert m.release_generation is not None  # validated as a pair by Manifest
        publication = binding_publications.BindingPublication(
            binding_id=binding.id,
            release_id=m.release_id,
            generation=m.release_generation,
            payload_hash=publications.canonical_hash(
                {
                    "schema_version": publications.SCHEMA_VERSION,
                    "operation": "binding_sync",
                    "binding_id": str(binding.id),
                    "asset_id": str(binding.asset_id),
                    "release_id": m.release_id,
                    "release_generation": m.release_generation,
                    "commit_sha": m.commit_sha,
                    "commit_timestamp": manifest_ts.astimezone(UTC).isoformat(),
                    "bundle_sha256": digest,
                }
            ),
            commit_sha=m.commit_sha,
        )
        replay = await binding_publications.replay_or_admit(session, binding, publication)
        if replay is not None:
            return replay
        binding.last_release_generation = m.release_generation

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
        binding_publication=publication,
        audit_action="binding_synced",
        audit_payload=lambda nv: {
            "commit_sha": m.commit_sha,
            "commit_timestamp": manifest_ts.isoformat(),
            "version": nv.version,
            "file_count": nv.file_count,
            "size_bytes": nv.size_bytes,
            "security": nv.security,
            **(
                {"release_id": publication.release_id, "release_generation": publication.generation}
                if publication is not None
                else {}
            ),
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

    return result.publication_result or {
        "version": result.version,
        "entry_path": result.entry_path,
        "file_count": result.file_count,
        "size_bytes": result.size_bytes,
        "commit_sha": m.commit_sha,
        "security_status": asset.security_status,
    }
