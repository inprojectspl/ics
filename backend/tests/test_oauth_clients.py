"""Tests for `oauth/clients.py`: seeding the built-in MCP clients."""

from __future__ import annotations

import pytest
from sqlalchemy import select


@pytest.mark.asyncio
async def test_ensure_builtin_clients_seeds_when_mcp_uri_set(session, monkeypatch):
    """With `mcp_resource_uri` set, builtin clients (stdio + http) are created
    if they do not exist."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings
    from app.db import Base
    from app.models import OAuthClient
    from app.oauth import clients as clients_mod

    s = get_settings()
    monkeypatch.setattr(s, "mcp_resource_uri", "https://ics-test.example/mcp-seed")

    engine = create_async_engine(s.database_url, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    await clients_mod.ensure_builtin_clients(factory, s)

    async with factory() as ses:
        stdio = await ses.scalar(
            select(OAuthClient).where(OAuthClient.client_id == "ics-mcp-stdio"),
        )
        http = await ses.scalar(
            select(OAuthClient).where(OAuthClient.client_id == "ics-mcp-http"),
        )
        assert stdio is not None
        assert http is not None
        assert "ics" in stdio.allowed_scopes

    # Idempotent: a second call does not blow up.
    await clients_mod.ensure_builtin_clients(factory, s)
    await engine.dispose()


@pytest.mark.asyncio
async def test_ensure_builtin_clients_noop_without_mcp_uri(session, monkeypatch):
    """Without `mcp_resource_uri` it is a no-op."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings
    from app.oauth import clients as clients_mod

    s = get_settings()
    monkeypatch.setattr(s, "mcp_resource_uri", "")

    engine = create_async_engine(s.database_url, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    await clients_mod.ensure_builtin_clients(factory, s)
    await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_seeding_leaves_one_row_per_builtin_client(session, monkeypatch):
    """Both uvicorn workers seed on startup at once; neither may fail and the
    unique client_id must not end up duplicated."""
    import asyncio

    from sqlalchemy import func
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings
    from app.models import OAuthClient
    from app.oauth import clients as clients_mod

    s = get_settings()
    monkeypatch.setattr(s, "mcp_resource_uri", "https://ics-test.example/mcp-race")
    engine = create_async_engine(s.database_url, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    await asyncio.gather(*(clients_mod.ensure_builtin_clients(factory, s) for _ in range(4)))

    async with factory() as ses:
        counts = dict(
            (
                await ses.execute(
                    select(OAuthClient.client_id, func.count())
                    .where(OAuthClient.client_id.in_(["ics-mcp-stdio", "ics-mcp-http"]))
                    .group_by(OAuthClient.client_id)
                )
            ).all()
        )
    await engine.dispose()
    assert counts == {"ics-mcp-stdio": 1, "ics-mcp-http": 1}
