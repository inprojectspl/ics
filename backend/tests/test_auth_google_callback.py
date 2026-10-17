"""Tests for `routes/auth/google.py`: the callback flow with a mocked Authlib.

E2E against real Google is out of scope (it needs real creds and an external
redirect). We mock `get_oauth().google` at module level:
`authorize_access_token` returns a controlled token payload, which lets us
walk every branch of the callback handler without network traffic.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import User
from app.slug import generate_slug
from tests.conftest import (
    mk_user,
)
from tests.conftest import (
    mock_google_oauth as _mock_oauth,
)
from tests.conftest import (
    patch_google_creds as _patch_google_creds,
)


@pytest.mark.asyncio
async def test_google_login_redirects_to_provider_when_configured(client, monkeypatch):
    """`/google/login` goes through `require_google_oidc` and calls
    `authorize_redirect`. We check that we get a 302 to Google."""
    _patch_google_creds(monkeypatch)
    monkeypatch.setattr("app.routes.auth.google.get_oauth", lambda: _mock_oauth({}))

    r = await client.get("/api/auth/google/login", follow_redirects=False)
    assert r.status_code == 302
    assert "accounts.google.com" in r.headers["location"]


@pytest.mark.asyncio
async def test_google_callback_authlib_error_returns_400_and_audits(client, session, monkeypatch):
    """When Authlib raises from `authorize_access_token` (state mismatch,
    expired code, network), the handler writes an audit log and returns 400."""
    _patch_google_creds(monkeypatch)
    monkeypatch.setattr(
        "app.routes.auth.google.get_oauth",
        lambda: _mock_oauth(raise_on_token=RuntimeError("state mismatch")),
    )

    r = await client.get("/api/auth/google/callback?code=x&state=y", follow_redirects=False)
    assert r.status_code == 400

    from app.models import AuditLog

    rows = (
        (
            await session.execute(
                select(AuditLog)
                .where(AuditLog.action == "login_failed")
                .order_by(AuditLog.timestamp.desc())
            )
        )
        .scalars()
        .all()
    )
    assert any(r.payload.get("reason") == "google_oauth_error" for r in rows)


@pytest.mark.asyncio
async def test_google_callback_missing_userinfo_returns_400(client, monkeypatch):
    _patch_google_creds(monkeypatch)
    monkeypatch.setattr(
        "app.routes.auth.google.get_oauth",
        lambda: _mock_oauth({}),  # no userinfo
    )

    r = await client.get("/api/auth/google/callback", follow_redirects=False)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_google_callback_missing_email_returns_400(client, monkeypatch):
    _patch_google_creds(monkeypatch)
    monkeypatch.setattr(
        "app.routes.auth.google.get_oauth",
        lambda: _mock_oauth({"userinfo": {"name": "User"}}),  # no email
    )

    r = await client.get("/api/auth/google/callback", follow_redirects=False)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_google_callback_unverified_email_returns_403(client, monkeypatch):
    """Missing `email_verified=True` (Google did not confirm the address) -> 403.
    The test guards against falling into a default-true via `.get(..., True)`:
    it must be an explicit True."""
    _patch_google_creds(monkeypatch)
    monkeypatch.setattr(
        "app.routes.auth.google.get_oauth",
        lambda: _mock_oauth(
            {"userinfo": {"email": "user@example.com", "email_verified": False, "name": "User"}}
        ),
    )

    r = await client.get("/api/auth/google/callback", follow_redirects=False)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_google_callback_domain_not_allowed_returns_403_and_audits(
    client, session, monkeypatch
):
    _patch_google_creds(monkeypatch)
    monkeypatch.setattr(
        "app.routes.auth.google.get_oauth",
        lambda: _mock_oauth(
            {"userinfo": {"email": "attacker@gmail.com", "email_verified": True, "name": "Mallory"}}
        ),
    )

    r = await client.get("/api/auth/google/callback", follow_redirects=False)
    assert r.status_code == 403

    from app.models import AuditLog

    rows = (
        (
            await session.execute(
                select(AuditLog)
                .where(AuditLog.action == "login_failed")
                .order_by(AuditLog.timestamp.desc())
            )
        )
        .scalars()
        .all()
    )
    assert any(r.payload.get("reason") == "domain_not_allowed" for r in rows)


@pytest.mark.asyncio
async def test_google_callback_creates_new_user_and_logs_in(client, session, monkeypatch):
    """Happy path first login: the user is not in the DB -> we create it with
    `auth_method=google_sso`, set the session cookie and redirect to base_url."""
    _patch_google_creds(monkeypatch)
    email = f"fresh+{generate_slug(6)}@example.com"
    monkeypatch.setattr(
        "app.routes.auth.google.get_oauth",
        lambda: _mock_oauth(
            {
                "userinfo": {
                    "email": email,
                    "email_verified": True,
                    "name": "Fresh User",
                    "picture": "https://lh3.googleusercontent.com/a/avatar.png",
                },
            }
        ),
    )

    r = await client.get("/api/auth/google/callback", follow_redirects=False)
    assert r.status_code == 302

    user = (await session.execute(select(User).where(User.email == email))).scalar_one()
    assert user.auth_method == "google_sso"
    assert user.display_name == "Fresh User"
    assert user.avatar_url == "https://lh3.googleusercontent.com/a/avatar.png"
    assert user.email_verified_at is not None
    assert user.last_login_at is not None

    # Session cookie is set: `/me` returns this user.
    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == email


@pytest.mark.asyncio
async def test_google_callback_links_password_account_and_refreshes_profile(
    client, session, monkeypatch
):
    """Account linking: a user with `auth_method=password` signs in via Google.
    Empty local display_name -> filled from Google. email_verified_at None ->
    set now. last_login_at is updated."""
    _patch_google_creds(monkeypatch)
    existing = await mk_user(
        session,
        email_verified=False,
        display_name="",
    )
    existing.avatar_url = None
    existing.email_verified_at = None
    await session.commit()

    monkeypatch.setattr(
        "app.routes.auth.google.get_oauth",
        lambda: _mock_oauth(
            {
                "userinfo": {
                    "email": existing.email,
                    "email_verified": True,
                    "name": "Linked Name",
                    "picture": "https://lh3.googleusercontent.com/a/linked.png",
                },
            }
        ),
    )

    r = await client.get("/api/auth/google/callback", follow_redirects=False)
    assert r.status_code == 302

    await session.refresh(existing)
    assert existing.display_name == "Linked Name"
    assert existing.avatar_url == "https://lh3.googleusercontent.com/a/linked.png"
    assert existing.email_verified_at is not None
    assert existing.auth_method == "password"  # we do not overwrite auth_method


@pytest.mark.asyncio
async def test_google_callback_clears_locked_until(client, session, monkeypatch):
    """A locked user (after rate-limit hammering) signs in with Google: the
    lockout is cleared because SSO succeeded despite the password fail count."""
    from datetime import UTC, datetime, timedelta

    _patch_google_creds(monkeypatch)
    existing = await mk_user(session)
    existing.locked_until = datetime.now(UTC) + timedelta(hours=1)
    await session.commit()

    monkeypatch.setattr(
        "app.routes.auth.google.get_oauth",
        lambda: _mock_oauth(
            {
                "userinfo": {
                    "email": existing.email,
                    "email_verified": True,
                    "name": existing.display_name,
                },
            }
        ),
    )

    r = await client.get("/api/auth/google/callback", follow_redirects=False)
    assert r.status_code == 302

    await session.refresh(existing)
    assert existing.locked_until is None


@pytest.mark.asyncio
async def test_google_callback_keeps_admin_lock(client, session, monkeypatch):
    """An administrator's lock is not a failed-password lockout: SSO must not lift it."""
    from datetime import UTC, datetime, timedelta

    from app import audit

    _patch_google_creds(monkeypatch)
    admin = await mk_user(session, role="admin")
    existing = await mk_user(session)
    until = datetime.now(UTC) + timedelta(hours=1)
    existing.locked_until = until
    await audit.record(
        session, actor=admin, action="user_locked_by_admin", target=f"user:{existing.id}"
    )
    await session.commit()

    monkeypatch.setattr(
        "app.routes.auth.google.get_oauth",
        lambda: _mock_oauth(
            {"userinfo": {"email": existing.email, "email_verified": True, "name": "X"}}
        ),
    )

    r = await client.get("/api/auth/google/callback", follow_redirects=False)
    assert r.status_code == 403
    assert r.json()["code"] == "account_locked"
    await session.refresh(existing)
    assert existing.locked_until == until


@pytest.mark.asyncio
async def test_google_callback_rejects_every_domain_without_allowlist(client, monkeypatch):
    """A deployment that never set ICS_ALLOWED_DOMAINS admits nobody via SSO."""
    from app.config import Settings, get_settings

    assert Settings(debug=True, allowed_domains="").allowed_domain_list == []
    monkeypatch.setattr(get_settings(), "allowed_domains", "")
    _patch_google_creds(monkeypatch)
    for email in ("someone@example.com", "someone@example.org"):
        monkeypatch.setattr(
            "app.routes.auth.google.get_oauth",
            lambda email=email: _mock_oauth(
                {"userinfo": {"email": email, "email_verified": True, "name": "X"}}
            ),
        )
        r = await client.get("/api/auth/google/callback", follow_redirects=False)
        assert r.status_code == 403


def test_settings_default_has_no_organisation_domains(monkeypatch):
    from app.config import Settings

    monkeypatch.delenv("ICS_ALLOWED_DOMAINS", raising=False)
    assert Settings(debug=True).allowed_domain_list == []


@pytest.mark.asyncio
async def test_google_callback_doesnt_overwrite_existing_display_name(client, session, monkeypatch):
    """User has a local display_name -> the Google name does not overwrite it."""
    from tests.conftest import mock_google_oauth, patch_google_creds

    patch_google_creds(monkeypatch)

    existing = await mk_user(session, display_name="Original Name")
    existing.avatar_url = "https://existing-avatar.png"
    await session.commit()

    monkeypatch.setattr(
        "app.routes.auth.google.get_oauth",
        lambda: mock_google_oauth(
            {
                "userinfo": {
                    "email": existing.email,
                    "email_verified": True,
                    "name": "Google's Name",
                    "picture": "https://google-pic.png",
                },
            }
        ),
    )

    r = await client.get("/api/auth/google/callback", follow_redirects=False)
    assert r.status_code == 302

    await session.refresh(existing)
    assert existing.display_name == "Original Name"
    assert existing.avatar_url == "https://existing-avatar.png"
