"""The ORM metadata matches the schema the migrations build.

Tests create tables from the metadata, production from migrations; drift
between them means tests run against a different schema and the next
`alembic revision --autogenerate` would drop real indexes.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import asyncpg

BACKEND = Path(__file__).resolve().parent.parent


async def _recreate(url: str, name: str) -> None:
    parsed = urlparse(url.replace("postgresql+asyncpg://", "postgresql://"))
    admin = await asyncpg.connect(
        user=parsed.username,
        password=parsed.password,
        host=parsed.hostname,
        port=parsed.port or 5432,
        database="postgres",
    )
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}"')
        await admin.execute(f'CREATE DATABASE "{name}"')
    finally:
        await admin.close()


def _alembic(*args: str, url: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "ICS_DATABASE_URL": url}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_migrations_and_models_describe_the_same_schema():
    base = os.environ["ICS_DATABASE_URL"]
    name = f"ics_drift_{os.environ.get('PYTEST_XDIST_WORKER', 'master')}"
    url = base.rsplit("/", 1)[0] + f"/{name}"
    asyncio.run(_recreate(base, name))

    upgrade = _alembic("upgrade", "head", url=url)
    assert upgrade.returncode == 0, upgrade.stderr
    check = _alembic("check", url=url)
    assert check.returncode == 0, check.stdout + check.stderr


async def test_project_slug_and_oauth_client_id_are_unique(session):
    import pytest
    from sqlalchemy.exc import IntegrityError

    from app.models import OAuthClient, Project
    from app.slug import generate_slug

    slug = generate_slug()
    session.add_all([Project(slug=slug, name="a"), Project(slug=slug, name="b")])
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()

    client_id = f"dup-{generate_slug()}"
    for _ in range(2):
        session.add(
            OAuthClient(
                client_id=client_id,
                name="x",
                client_type="public",
                redirect_uris=["http://localhost/cb"],
                allowed_audiences=["http://ics.test/mcp"],
            )
        )
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()
