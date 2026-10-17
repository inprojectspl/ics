"""Tests for `app/cli.py`: operational commands (seed-admin, outbox-tail)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app import cli, passwords
from app.models import EmailOutbox, User
from app.slug import generate_slug


@pytest.fixture
def cli_sessions(session, monkeypatch):
    """Point the CLI at the per-test engine.

    `app.cli` opens sessions from the module-level `app.db.SessionLocal`,
    whose pool keeps asyncpg connections bound to the event loop that
    created them. pytest-asyncio gives every test a fresh loop, so a pooled
    connection from an earlier test fails here. The per-test engine behind
    the `session` fixture lives on the current loop.
    """
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    monkeypatch.setattr(cli, "SessionLocal", factory)
    return factory


async def _load_user(factory, email: str) -> User:
    async with factory() as s:
        return (await s.execute(select(User).where(User.email == email))).scalar_one()


@pytest.mark.asyncio
async def test_cli_seed_admin_creates_new_admin(cli_sessions):
    email = f"newadmin+{generate_slug(6)}@example.com"
    await cli.seed_admin(email, "ValidStrong-Pass-1!", "Test Admin")

    user = await _load_user(cli_sessions, email)
    assert user.role == "admin"
    assert user.display_name == "Test Admin"
    assert passwords.verify_password("ValidStrong-Pass-1!", user.password_hash)


@pytest.mark.asyncio
async def test_cli_seed_admin_updates_existing_user_to_admin(cli_sessions, session):
    email = f"existing+{generate_slug(8)}@example.com"
    session.add(User(email=email, display_name="Plain", role="user", auth_method="google_sso"))
    await session.commit()

    await cli.seed_admin(email, "NewStrong-Pass-2!", None)

    user = await _load_user(cli_sessions, email)
    assert user.role == "admin"
    assert user.auth_method == "password"
    assert user.email_verified_at is not None
    assert passwords.verify_password("NewStrong-Pass-2!", user.password_hash)


@pytest.mark.asyncio
async def test_cli_seed_admin_rejects_weak_password(cli_sessions):
    email = f"weak+{generate_slug(6)}@example.com"
    with pytest.raises(passwords.WeakPasswordError):
        await cli.seed_admin(email, "short", None)

    async with cli_sessions() as s:
        assert await s.scalar(select(User).where(User.email == email)) is None


@pytest.mark.asyncio
async def test_cli_outbox_tail_prints_latest_messages(cli_sessions, session, capsys):
    to_email = f"outbox+{generate_slug(6)}@example.com"
    session.add(EmailOutbox(to_email=to_email, subject="s", body="b", purpose="invite"))
    await session.commit()

    await cli.outbox_tail(limit=5)
    assert to_email in capsys.readouterr().out


def test_cli_main_outbox_dispatch_smoke(monkeypatch):
    """Smoke for the `main()` parser path of outbox-tail. We do not call
    asyncio.run() from inside the pytest-asyncio loop; instead we parse argv
    directly to cover argparse + dispatch branches."""
    import sys

    from app import cli

    # Replace asyncio.run with a no-op so it does not fail on the running loop.
    monkeypatch.setattr("app.cli.asyncio.run", lambda coro: coro.close() or None)
    test_argv = ["app.cli", "outbox-tail", "--limit", "1"]
    monkeypatch.setattr(sys, "argv", test_argv)
    cli.main()


def test_cli_main_seed_admin_dispatch_smoke(monkeypatch):
    import sys

    from app import cli

    monkeypatch.setattr("app.cli.asyncio.run", lambda coro: coro.close() or None)
    test_argv = [
        "app.cli",
        "seed-admin",
        "--email",
        "x@example.com",
        "--password",
        "Strong-Pass-3!",
    ]
    monkeypatch.setattr(sys, "argv", test_argv)
    cli.main()
