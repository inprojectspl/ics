"""audit_log is append-only in the database itself, not just in app code."""

from __future__ import annotations

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError

from app.models import AuditLog
from app.slug import generate_slug


async def _entry(session) -> int:
    row = AuditLog(actor=f"test-{generate_slug(6)}", action="test.append_only")
    session.add(row)
    await session.commit()
    return row.id


@pytest.mark.asyncio
async def test_update_is_refused(session):
    entry_id = await _entry(session)

    with pytest.raises(DBAPIError, match="audit_log is append-only"):
        async with session.begin_nested():
            await session.execute(
                update(AuditLog).where(AuditLog.id == entry_id).values(actor="rewritten")
            )
    await session.rollback()

    actor = await session.scalar(select(AuditLog.actor).where(AuditLog.id == entry_id))
    assert actor != "rewritten"


@pytest.mark.asyncio
async def test_delete_is_refused(session):
    entry_id = await _entry(session)

    with pytest.raises(DBAPIError, match="audit_log is append-only"):
        async with session.begin_nested():
            await session.execute(delete(AuditLog).where(AuditLog.id == entry_id))
    await session.rollback()

    assert await session.scalar(select(AuditLog.id).where(AuditLog.id == entry_id)) == entry_id
