import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.audit import actor_label, record
from app.config import get_settings
from app.db import Base
from app.models import AuditLog, User
from app.slug import generate_slug


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(get_settings().database_url, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


def test_actor_label_user_uses_email():
    u = User(email="alice@example.com", display_name="Alice", role="user")
    assert actor_label(u) == "user:alice@example.com"


def test_actor_label_none_is_anonymous():
    assert actor_label(None) == "anonymous"


def test_actor_label_string_passthrough():
    assert actor_label("system") == "system"
    assert actor_label("user_id:abc") == "user_id:abc"


@pytest.mark.asyncio
async def test_record_writes_row_without_committing(session):
    u = User(email=f"a+{generate_slug(6)}@example.com", display_name="a", role="user")
    session.add(u)
    await session.flush()

    await record(
        session,
        actor=u,
        action="test_action",
        target=f"user:{u.id}",
        payload={"foo": "bar"},
        ip_hash="abc123",
    )
    # not committed yet, but flush should produce the insert
    await session.flush()
    rows = (await session.execute(select(AuditLog))).scalars().all()
    matching = [r for r in rows if r.action == "test_action"]
    assert len(matching) == 1
    r = matching[0]
    assert r.actor == f"user:{u.email}"
    assert r.target == f"user:{u.id}"
    assert r.payload == {"foo": "bar"}
    assert r.ip_hash == "abc123"


@pytest.mark.asyncio
async def test_record_rolls_back_with_outer_transaction(session):
    """Audit row must die with the action it describes (no orphan logs)."""
    await record(session, actor="test", action="rolled_back_event")
    await session.flush()
    await session.rollback()
    rows = (
        (await session.execute(select(AuditLog).where(AuditLog.action == "rolled_back_event")))
        .scalars()
        .all()
    )
    assert rows == []
