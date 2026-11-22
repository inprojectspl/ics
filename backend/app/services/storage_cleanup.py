"""Deleting the files of rows that are gone for good (`StorageCleanup`).

`schedule` runs in the transaction that removes the rows; `run` after its
commit, and `sweep` from the worker for whatever a crash or a storage error
left behind. Deleting a prefix is idempotent, so two runs may overlap.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence

import structlog
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import StorageCleanup
from app.storage import delete_prefixes, storage_from_url

log = structlog.get_logger(__name__)

_BATCH = 200
# Entries one request deletes itself; a larger account waits for the worker.
INLINE_MAX = 200

Entry = tuple[int, str]


async def schedule(session: AsyncSession, prefixes: Collection[str], *, reason: str) -> list[Entry]:
    """Record `prefixes` for deletion; returns the entries to `run` after the commit."""
    rows = [StorageCleanup(prefix=p, reason=reason) for p in sorted(prefixes)]
    session.add_all(rows)
    await session.flush()
    return [(r.id, r.prefix) for r in rows]


async def run(session: AsyncSession, settings: Settings, entries: Sequence[Entry]) -> int:
    """Delete the files of `entries` and drop the entries that succeeded;
    a failed one stays for `sweep` with its attempt counted. Commits; no
    transaction stays open through the storage calls. Returns how many are done."""
    await session.commit()
    if not entries:
        return 0
    outcomes = await delete_prefixes(
        storage_from_url(settings.storage_url), [p for _, p in entries], raise_first=False
    )
    done = []
    for (entry_id, prefix), outcome in zip(entries, outcomes, strict=True):
        if outcome is None:
            done.append(entry_id)
            continue
        log.warning("storage_cleanup.failed", prefix=prefix, error=repr(outcome))
        await session.execute(
            update(StorageCleanup)
            .where(StorageCleanup.id == entry_id)
            .values(attempts=StorageCleanup.attempts + 1, last_error=repr(outcome)[:500])
        )
    if done:
        await session.execute(delete(StorageCleanup).where(StorageCleanup.id.in_(done)))
    await session.commit()
    return len(done)


async def sweep(session: AsyncSession, settings: Settings, *, batches: int = 10) -> int:
    """Retry pending entries, the least tried first, so prefixes that keep
    failing do not hold back the rest. Returns how many were done."""
    cleaned = 0
    for _ in range(batches):
        entries = [
            (row.id, row.prefix)
            for row in await session.execute(
                select(StorageCleanup.id, StorageCleanup.prefix)
                .order_by(StorageCleanup.attempts, StorageCleanup.id)
                .limit(_BATCH)
            )
        ]
        done = await run(session, settings, entries)
        cleaned += done
        if len(entries) < _BATCH or not done:
            break
    return cleaned
