"""Security scanning of HTML bundles, documents (PDF, Office) and Markdown."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, cdn_allowlist
from app.bundle_scan import apply_scan_if_html, prompt_injection
from app.collections_io import MarkdownSources
from app.config import Settings
from app.models import Asset, User
from app.services import documents
from app.util import now as utc_now

AUTO_BYPASS_REASON = "auto-accepted: the uploader has html_autobypass enabled"


def publication_blocked(asset: Asset) -> bool:
    """Whether the bundle awaits admin approval and must not be shared. The
    only place where the scanner status is combined with the bypass."""
    return asset.security_status == "critical" and not asset.security_bypass


async def scan_and_apply(
    asset: Asset,
    settings: Settings,
    session: AsyncSession,
    *,
    actor: User | None = None,
    markdown_sources: MarkdownSources | None = None,
) -> dict | None:
    """Scan the asset and store the result in `asset.security_*`; returns a
    summary, or None when the kind needs no scan. Documents are scanned by
    their conversion child process at write time, so this only stores those
    findings. Markdown gets only the advisory prompt-injection rule."""
    summary: dict | None
    if documents.is_document(asset.kind):
        summary = await documents.apply_scan(asset, settings)
    elif asset.kind == "html_bundle":
        trusted = await cdn_allowlist.trusted_hosts(session, settings)
        summary = await apply_scan_if_html(asset, settings, trusted_hosts=trusted)
    elif prompt_injection.is_markdown_kind(asset.kind):
        # Advisory only (warn at most), so it never reaches the bypass below.
        report = await prompt_injection.scan_markdown_asset(
            asset, settings, sources=markdown_sources
        )
        return prompt_injection.apply_markdown_report(asset, report)
    else:
        return None

    # Auto-approval only grants the bypass and keeps the findings, so the admin
    # still sees them and `revoke` undoes it like a manual bypass.
    if actor is not None and actor.html_autobypass and asset.security_status == "critical":
        asset.security_bypass = True
        asset.security_bypass_at = utc_now()
        asset.security_bypass_by = actor.id
        asset.security_bypass_reason = AUTO_BYPASS_REASON
        await audit.record(
            session,
            actor=actor,
            action="security_bypass_granted",
            target=f"asset:{asset.id}",
            payload={
                "auto": True,
                "reason": AUTO_BYPASS_REASON,
                "findings": (summary or {}).get("critical_count"),
            },
        )
        if summary is not None:
            summary["auto_bypass"] = True
    return summary
