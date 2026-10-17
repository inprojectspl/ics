"""Tests for `app/auth.py`: user lookup and creation through the dev SSO stub."""

from __future__ import annotations

import pytest

from app.slug import generate_slug
from tests.conftest import mk_user


@pytest.mark.asyncio
async def test_dev_stub_creates_new_user_when_not_existing(client, session, monkeypatch):
    """First use of x-dev-user for a non-existent email -> creates a user
    with auth_method=google_sso, email_verified_at=now."""
    from sqlalchemy import select

    from app.config import get_settings
    from app.models import User

    s = get_settings()
    monkeypatch.setattr(s, "dev_stub_sso", True)

    email = f"new+{generate_slug(6)}@example.com"
    r = await client.get(
        "/api/auth/oauth/me",
        headers={"X-Dev-User": email},
    )
    assert r.status_code == 200
    assert r.json()["email"] == email

    # User was created in the DB
    user = (await session.execute(select(User).where(User.email == email))).scalar_one()
    assert user.auth_method == "google_sso"
    assert user.email_verified_at is not None
    assert user.last_login_at is not None


@pytest.mark.asyncio
async def test_dev_stub_returning_user_just_bumps_last_login(client, session, monkeypatch):
    """Second x-dev-user call for an existing user -> reuse + bump last_login_at."""
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "dev_stub_sso", True)

    existing = await mk_user(session, email=f"existing+{generate_slug(6)}@example.com")
    original_last_login = existing.last_login_at
    await session.commit()

    r = await client.get(
        "/api/auth/oauth/me",
        headers={"X-Dev-User": existing.email},
    )
    assert r.status_code == 200

    await session.refresh(existing)
    # last_login_at bumped
    if original_last_login is None:
        assert existing.last_login_at is not None
    else:
        assert existing.last_login_at > original_last_login
