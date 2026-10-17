"""Admin-only endpoints: audit log viewer + security review queue +
CDN allowlist management."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, cdn_allowlist
from app.auth import AdminUser
from app.bundle_scan import localize_report
from app.config import Settings, get_settings
from app.constants import AUDIT_ACTIONS
from app.db import get_session
from app.errors import ApiError
from app.i18n import Locale, resolve_locale
from app.i18n.request import AcceptLanguage
from app.models import Asset, AuditLog, CdnAllowlist, User
from app.services.audit_labels import RefInfo, payload_refs, resolve_refs
from app.util import now as utc_now

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/audit/actions")
async def list_audit_actions(_admin: AdminUser) -> list[str]:
    """Canonical action vocabulary; the frontend uses this for the filter
    dropdown so the list never drifts from the backend's emit sites."""
    return list(AUDIT_ACTIONS)


def _ref_fields(refs: dict[str, RefInfo], prefix: str, value: str | None) -> dict:
    """`<prefix>_label` and `<prefix>_href` of one audit reference, null when unresolved."""
    info = refs.get(value) if value else None
    return {
        f"{prefix}_label": info.label if info else None,
        f"{prefix}_href": info.href if info else None,
    }


@router.get("/audit")
async def list_audit(
    _admin: AdminUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    action: Annotated[str | None, Query()] = None,
    actor: Annotated[str | None, Query(description="exact match")] = None,
    target: Annotated[str | None, Query(description="prefix match, e.g. user: or share:")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    before_id: Annotated[int | None, Query(description="cursor: id < before_id")] = None,
) -> dict:
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if actor:
        stmt = stmt.where(AuditLog.actor == actor)
    if target:
        stmt = stmt.where(AuditLog.target.like(f"{target}%"))
    if before_id is not None:
        stmt = stmt.where(AuditLog.id < before_id)

    rows = (await session.execute(stmt)).scalars().all()
    in_payload = {r.id: payload_refs(r.action, r.payload) for r in rows}
    refs = await resolve_refs(
        session,
        [ref for r in rows for ref in (r.actor, r.target)]
        + [ref for fields in in_payload.values() for values in fields.values() for ref in values],
    )

    return {
        "items": [
            {
                "id": r.id,
                "timestamp": r.timestamp.isoformat(),
                "actor": r.actor,
                **_ref_fields(refs, "actor", r.actor),
                "action": r.action,
                "target": r.target,
                **_ref_fields(refs, "target", r.target),
                "payload": r.payload,
                # Names and links for payload ids, per field; unresolved ids are left out.
                "payload_refs": {
                    key: [
                        {"label": i.label, "href": i.href} for ref in values if (i := refs.get(ref))
                    ]
                    for key, values in in_payload[r.id].items()
                },
                "ip_hash": r.ip_hash,
            }
            for r in rows
        ],
        "next_cursor": rows[-1].id if len(rows) == limit else None,
    }


# ---------- Security review queue ----------


class BypassIn(BaseModel):
    reason: str = Field(min_length=8, max_length=2000)


def _asset_review_row(a: Asset, locale: Locale, owner_email: str | None) -> dict:
    return {
        "id": str(a.id),
        "slug": a.slug,
        "title": a.title,
        "kind": a.kind,
        "owner_id": str(a.owner_id),
        "owner_email": owner_email,
        "version": a.version,
        "size_bytes": a.size_bytes,
        "security_status": a.security_status,
        "security_report": localize_report(a.security_report, locale),
        "security_bypass": a.security_bypass,
        "security_bypass_at": a.security_bypass_at.isoformat() if a.security_bypass_at else None,
        "security_bypass_by": str(a.security_bypass_by) if a.security_bypass_by else None,
        "security_bypass_reason": a.security_bypass_reason,
        "created_at": a.created_at.isoformat(),
        "updated_at": a.updated_at.isoformat(),
    }


async def _review_row(session: AsyncSession, asset: Asset, locale: Locale) -> dict:
    owner = await session.get(User, asset.owner_id)
    return _asset_review_row(asset, locale, owner.email if owner else None)


@router.get("/review")
async def list_review_queue(
    admin: AdminUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    accept_language: AcceptLanguage = None,
) -> list[dict]:
    """Assets flagged `critical` by the bundle scanner and not yet bypassed.
    Backed by the `ix_assets_security_pending` partial index."""
    rows = (
        await session.execute(
            select(Asset, User.email)
            .outerjoin(User, User.id == Asset.owner_id)
            .where(
                Asset.security_status == "critical",
                Asset.security_bypass.is_(False),
                Asset.deleted_at.is_(None),
            )
            .order_by(Asset.created_at.desc())
            .limit(limit)
        )
    ).all()
    locale = resolve_locale(admin.locale, accept_language=accept_language)
    return [_asset_review_row(a, locale, email) for a, email in rows]


@router.get("/assets/{asset_id}/review")
async def get_review_detail(
    asset_id: UUID,
    admin: AdminUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    accept_language: AcceptLanguage = None,
) -> dict:
    asset = await session.get(Asset, asset_id)
    if asset is None or asset.deleted_at is not None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "asset_not_found", "asset not found")
    return await _review_row(
        session, asset, resolve_locale(admin.locale, accept_language=accept_language)
    )


@router.post("/assets/{asset_id}/security-bypass")
async def grant_security_bypass(
    asset_id: UUID,
    body: BypassIn,
    admin: AdminUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    accept_language: AcceptLanguage = None,
) -> dict:
    """Admin reviews scan findings, accepts the risk, and unblocks share
    creation. The decision is permanent for this version: re-uploading
    or syncing a new version re-runs the scan and clears the bypass."""
    asset = await session.get(Asset, asset_id)
    if asset is None or asset.deleted_at is not None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "asset_not_found", "asset not found")
    if asset.security_status != "critical":
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "bypass_not_applicable",
            "a bypass applies only to assets flagged critical",
        )
    if asset.security_bypass:
        raise ApiError(status.HTTP_409_CONFLICT, "bypass_already_granted", "bypass already granted")

    asset.security_bypass = True
    asset.security_bypass_at = utc_now()
    asset.security_bypass_by = admin.id
    asset.security_bypass_reason = body.reason.strip()
    await audit.record(
        session,
        actor=admin,
        action="security_bypass_granted",
        target=f"asset:{asset.id}",
        payload={
            "version": asset.version,
            "reason": body.reason.strip(),
            "findings_count": len((asset.security_report or {}).get("findings", [])),
        },
    )
    await session.commit()
    # onupdate=func.now() expires the column after commit; refresh so the
    # response can read it without a lazy load from sync attribute access.
    await session.refresh(asset)
    return await _review_row(
        session, asset, resolve_locale(admin.locale, accept_language=accept_language)
    )


# ---------- CDN allowlist ----------


class CdnAddIn(BaseModel):
    host: str = Field(min_length=3, max_length=255)
    note: str | None = Field(default=None, max_length=500)


@router.get("/cdn-allowlist")
async def list_cdn_allowlist(
    _admin: AdminUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    """Returns the effective union of built-in + runtime hosts. The two
    sources are tagged separately so the UI can render built-ins as
    read-only chips next to admin-added editable rows."""
    rows = (
        (await session.execute(select(CdnAllowlist).order_by(CdnAllowlist.created_at.desc())))
        .scalars()
        .all()
    )
    return {
        "builtin": sorted(settings.trusted_cdn_hosts_set),
        "runtime": [
            {
                "id": str(r.id),
                "host": r.host,
                "note": r.note,
                "added_by": str(r.added_by) if r.added_by else None,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }


@router.post("/cdn-allowlist", status_code=status.HTTP_201_CREATED)
async def add_cdn_host(
    body: CdnAddIn,
    admin: AdminUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    host = body.host.strip().lower()
    if not cdn_allowlist.is_acceptable_host(host):
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "invalid_cdn_host",
            "invalid host: a dotted domain without scheme, port or path is required",
        )
    # Built-ins are rejected so the table holds no duplicates.
    if host in settings.trusted_cdn_hosts_set:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "cdn_host_builtin",
            f"{host} is already a built-in trusted host",
        )
    existing = (
        await session.execute(select(CdnAllowlist).where(CdnAllowlist.host == host))
    ).scalar_one_or_none()
    if existing is not None:
        raise ApiError(
            status.HTTP_409_CONFLICT, "cdn_host_exists", f"{host} is already on the list"
        )
    entry = CdnAllowlist(host=host, added_by=admin.id, note=body.note)
    session.add(entry)
    await audit.record(
        session,
        actor=admin,
        action="cdn_allowlist_added",
        target=f"cdn:{host}",
        payload={"note": body.note},
    )
    await session.commit()
    cdn_allowlist.invalidate()
    return {"id": str(entry.id), "host": host}


@router.delete("/cdn-allowlist/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_cdn_host(
    entry_id: UUID,
    admin: AdminUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    entry = await session.get(CdnAllowlist, entry_id)
    if entry is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "cdn_host_not_found", "CDN host not found")
    host = entry.host
    await audit.record(
        session,
        actor=admin,
        action="cdn_allowlist_removed",
        target=f"cdn:{host}",
    )
    await session.delete(entry)
    await session.commit()
    cdn_allowlist.invalidate()


@router.delete("/assets/{asset_id}/security-bypass", status_code=status.HTTP_200_OK)
async def revoke_security_bypass(
    asset_id: UUID,
    admin: AdminUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    accept_language: AcceptLanguage = None,
) -> dict:
    """Reverse an earlier bypass, e.g. after the owner reports the
    bundle is actually compromised. Active share links continue to work
    (the gate only fires at creation); revoke them separately if needed."""
    asset = await session.get(Asset, asset_id)
    if asset is None or asset.deleted_at is not None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "asset_not_found", "asset not found")
    if not asset.security_bypass:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "bypass_not_granted", "the asset has no bypass")

    asset.security_bypass = False
    asset.security_bypass_at = None
    asset.security_bypass_by = None
    asset.security_bypass_reason = None
    await audit.record(
        session,
        actor=admin,
        action="security_bypass_revoked",
        target=f"asset:{asset.id}",
        payload={"version": asset.version},
    )
    await session.commit()
    await session.refresh(asset)
    return await _review_row(
        session, asset, resolve_locale(admin.locale, accept_language=accept_language)
    )
