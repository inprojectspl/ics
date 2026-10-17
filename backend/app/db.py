import os
from collections.abc import AsyncIterator

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
