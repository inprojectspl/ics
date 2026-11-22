import os
from collections.abc import AsyncIterator, Iterable
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, Uuid, any_, literal, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()

# Pre-ping and recycle survive NAT drops and PG idle timeouts; JIT only slows short
# OLTP queries. The pool is smaller under xdist to fit PG's max_connections=100.
_in_xdist = bool(os.environ.get("PYTEST_XDIST_WORKER"))
engine = create_async_engine(
    _settings.database_url,
    echo=_settings.debug,
    future=True,
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_size=5 if _in_xdist else 20,
    max_overflow=5 if _in_xdist else 10,
    connect_args={"server_settings": {"jit": "off"}},
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


def uuid_in(column: Any, ids: Iterable[UUID]) -> ColumnElement[bool]:
    """`column IN ids` as one array parameter. An expanded IN binds one
    parameter per id, and asyncpg allows 32,767; use this wherever the list
    comes from data (backlinks, an account's assets)."""
    return column == any_(literal(list(ids), ARRAY(Uuid())))


async def advisory_xact_lock(session: AsyncSession, key: str) -> None:
    """Transaction-scoped advisory lock named by `key` (prefix it with
    `ics:<area>:`). A hash collision only serializes two unrelated keys."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key}
    )
