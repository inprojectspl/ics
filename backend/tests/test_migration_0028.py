"""Migration 0028 merges duplicate OAuth clients left by the startup race
before it restores the unique index on client_id."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from app.models import AuditLog, OAuthClient, OAuthRefreshToken
from app.slug import generate_slug
from tests.conftest import mk_user

_PATH = Path(__file__).parents[1] / "migrations/versions/0028_restore_unique_slug_and_client_id.py"
_spec = importlib.util.spec_from_file_location("migration_0028", _PATH)
assert _spec and _spec.loader
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)


def _client(client_id: str, created_at: datetime) -> OAuthClient:
    return OAuthClient(
        id=uuid4(),
        client_id=client_id,
        name="dup",
        client_type="public",
        redirect_uris=["http://127.0.0.1:*/callback"],
        allowed_scopes=["ics"],
        allowed_audiences=["https://ics-test.example/mcp"],
        created_at=created_at,
    )


@pytest.mark.asyncio
async def test_duplicates_are_merged_into_the_oldest_active_row(session):
    user = await mk_user(session)
    user_id = user.id
    client_id = f"dup-{generate_slug(6)}"
    now = datetime.now(UTC)
    await session.execute(text("DROP INDEX ix_oauth_clients_client_id"))
    try:
        keep, extra = _client(client_id, now - timedelta(days=1)), _client(client_id, now)
        session.add_all([keep, extra])
        await session.flush()
        keep_id, extra_id = keep.id, extra.id
        session.add(
            OAuthRefreshToken(
                id=uuid4(),
                token_hash=generate_slug(40),
                client_id=extra_id,
                user_id=user_id,
                scopes=["ics"],
                resource="https://ics-test.example/mcp",
                jwt_id=generate_slug(20),
                expires_at=now + timedelta(days=1),
            )
        )
        session.add(AuditLog(actor="t", action="asset.read", client_id=extra_id))
        await session.flush()

        for statement in migration.MERGE_DUPLICATE_CLIENTS:
            await session.execute(text(statement))
    finally:
        await session.execute(
            text("CREATE UNIQUE INDEX ix_oauth_clients_client_id ON oauth_clients (client_id)")
        )
    await session.commit()
    # The merge ran as plain SQL; drop the stale ORM copies.
    session.expire_all()

    active = await session.scalar(
        select(func.count())
        .select_from(OAuthClient)
        .where(OAuthClient.client_id == client_id, OAuthClient.revoked_at.is_(None))
    )
    token_client = await session.scalar(
        select(OAuthRefreshToken.client_id).where(OAuthRefreshToken.user_id == user_id)
    )
    renamed = (
        await session.execute(
            select(OAuthClient.client_id, OAuthClient.revoked_at).where(OAuthClient.id == extra_id)
        )
    ).one()
    audit_client = await session.scalar(
        select(AuditLog.client_id).where(AuditLog.client_id == extra_id)
    )
    assert active == 1
    assert token_client == keep_id
    assert renamed.revoked_at is not None and renamed.client_id != client_id
    assert audit_client == extra_id
