"""Arq tasks: expired OAuth artifacts and e-mail outbox retention.

audit_log is deliberately not cleaned: an immutability trigger (migration
0016) blocks DELETE, so retention there is a deliberate owner decision.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import CursorResult, delete

from app.db import SessionLocal
from app.models import EmailOutbox
from app.oauth import tokens as oauth_tokens


async def cleanup_oauth_artifacts(ctx: dict) -> dict:
    async with SessionLocal() as session:
        deleted = await oauth_tokens.cleanup_expired(session)
        await session.commit()
    return {"deleted": deleted}


async def cleanup_old_email_outbox(ctx: dict, *, days: int = 30) -> dict:
    """Drop sent email_outbox rows older than `days`. Bodies carry tokens
    (magic link, invite, reset), so short retention limits backup exposure."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    async with SessionLocal() as session:
        result = await session.execute(
            delete(EmailOutbox).where(
                EmailOutbox.sent_at.is_not(None),
                EmailOutbox.created_at < cutoff,
            )
        )
        await session.commit()
        deleted = cast(CursorResult, result).rowcount or 0
        return {"deleted": deleted, "cutoff": cutoff.isoformat()}
