"""The bootstrap admin is created once even when both uvicorn workers seed
it at the same moment on the first start of a fresh install."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bootstrap import ensure_bootstrap_admin
from app.config import get_settings
from app.models import User
from app.slug import generate_slug


@pytest.mark.asyncio
async def test_concurrent_first_start_creates_one_admin(session, monkeypatch):
    s = get_settings()
    email = f"boot+{generate_slug(6)}@example.com"
    monkeypatch.setattr(s, "bootstrap_admin_email", email)
    monkeypatch.setattr(s, "bootstrap_admin_password", "long enough passphrase")
    engine = create_async_engine(s.database_url, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    await asyncio.gather(*(ensure_bootstrap_admin(factory, s) for _ in range(4)))

    async with factory() as ses:
        count = await ses.scalar(select(func.count()).select_from(User).where(User.email == email))
        role = await ses.scalar(select(User.role).where(User.email == email))
    await engine.dispose()
    assert count == 1
    assert role == "admin"
