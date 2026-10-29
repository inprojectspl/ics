"""Tests for `routes/auth.py`: the key authentication paths.

Covers:
- /api/auth/config: feature flags for the frontend (public).
- /api/auth/me + /me/quota: gated by the session.
- /api/auth/login: happy path, bad password, unknown user, account locked,
  unverified email.
- /api/auth/logout: idempotent, clears the session.
- /api/auth/password-reset/{request,confirm}: token flow.
- /api/auth/invite + /setup: admin creates the account, user activates it with a token.
- /api/auth/register: gated by `ICS_ALLOW_SELF_REGISTER`.
- /api/auth/verify: marks the account as verified.
- /api/auth/google/login: 503 when OIDC is not configured.

Uses the httpx ASGI client from conftest.py; the session persists in the cookie jar.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select

from app import passwords, tokens
from app.models import User
from app.slug import generate_slug
from tests.conftest import mk_admin, mk_user


def _login_payload(email: str, password: str = "TestPass123!") -> dict:
    return {"email": email, "password": password}


def _uniq_email(prefix: str = "u") -> str:
    """Tables persist between tests, so a random slug keeps emails unique."""
    return f"{prefix}+{generate_slug(6)}@example.com"


async def _login(client, user: User, password: str = "TestPass123!") -> None:
    """Shortcut: POST /login + assert that a session was issued."""
    r = await client.post("/api/auth/login", json=_login_payload(user.email, password))
    assert r.status_code == 200, r.text


# ---------- /config (public) ----------


@pytest.mark.asyncio
async def test_auth_config_exposes_feature_flags(client):
    r = await client.get("/api/auth/config")
    assert r.status_code == 200
    body = r.json()
    assert {"google_oidc_enabled", "self_register_enabled", "dev_stub_sso"} <= body.keys()
    for key in ("google_oidc_enabled", "self_register_enabled", "dev_stub_sso"):
        assert isinstance(body[key], bool)


# ---------- /me + /me/quota (gated) ----------


@pytest.mark.asyncio
async def test_me_returns_401_when_anonymous(client):
    r = await client.get("/api/auth/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_me_quota_returns_401_when_anonymous(client):
    r = await client.get("/api/auth/me/quota")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_me_returns_user_profile_when_logged_in(client, session):
    user = await mk_user(session)
    await session.commit()

    await _login(client, user)
    r = await client.get("/api/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == user.email
    assert body["role"] == "user"
    assert body["email_verified"] is True


@pytest.mark.asyncio
async def test_me_quota_returns_zero_for_new_user(client, session):
    user = await mk_user(session)
    await session.commit()

    await _login(client, user)
    r = await client.get("/api/auth/me/quota")
    assert r.status_code == 200
    body = r.json()
    assert body["used_bytes"] == 0
    assert body["quota_bytes"] > 0


# ---------- /login ----------


@pytest.mark.asyncio
async def test_login_succeeds_with_correct_password(client, session):
    user = await mk_user(session, password="StrongPass1!")
    await session.commit()

    r = await client.post("/api/auth/login", json=_login_payload(user.email, "StrongPass1!"))
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    # Cookie issued -> subsequent requests are logged in.
    me = await client.get("/api/auth/me")
    assert me.status_code == 200


@pytest.mark.asyncio
async def test_login_fails_with_wrong_password(client, session):
    user = await mk_user(session, password="RealPass1!")
    await session.commit()

    r = await client.post("/api/auth/login", json=_login_payload(user.email, "WrongPass1!"))
    assert r.status_code == 401
    # Generic message: does not leak whether the email exists.
    assert r.json()["code"] == "invalid_credentials"


@pytest.mark.asyncio
async def test_login_fails_for_unknown_email(client):
    """No account -> 401, exactly the same payload as bad-password (anti-enumeration)."""
    r = await client.post(
        "/api/auth/login",
        json=_login_payload(_uniq_email("ghost"), "WhateverPass1!"),
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_login_rejects_unverified_email(client, session):
    user = await mk_user(session, password="VerifyMe1!", email_verified=False)
    await session.commit()

    r = await client.post("/api/auth/login", json=_login_payload(user.email, "VerifyMe1!"))
    assert r.status_code == 403
    assert r.json()["code"] == "account_unverified"


# ---------- /logout ----------


@pytest.mark.asyncio
async def test_logout_clears_session(client, session):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    r = await client.post("/api/auth/logout")
    assert r.status_code == 200
    # After logout /me must be 401 again.
    me = await client.get("/api/auth/me")
    assert me.status_code == 401


@pytest.mark.asyncio
async def test_logout_idempotent_when_anonymous(client):
    """Anonymous callers get 200 too, which makes 'always log in fresh' easy for clients."""
    r = await client.post("/api/auth/logout")
    assert r.status_code == 200


# ---------- Server-side session revocation (CWE-613) ----------


@pytest.mark.asyncio
async def test_stolen_cookie_loses_validity_after_logout(client, session):
    """An attacker copies the cookie of an active session. The victim logs
    out via `/api/auth/logout`. Without server-side revocation the stolen
    cookie would stay cryptographically valid (Starlette stateless signed
    cookies). The sid is in the revoked store, so /me returns 401."""
    user = await mk_user(session)
    await session.commit()

    # The victim logs in. We simulate cookie theft by taking the raw value,
    # call /me with an explicit Cookie header (like an attacker in another
    # browser) and check that it works; then the victim logs out and a
    # second request with the same cookie must be 401.
    await _login(client, user)
    stolen = client.cookies.get("session")
    assert stolen is not None

    # Same client, but a request with an explicit Cookie: checks that we
    # rely on the server-side check, not on the browser cookie jar.
    r = await client.get("/api/auth/me", headers={"Cookie": f"session={stolen}"})
    assert r.status_code == 200

    # The victim logs out.
    await client.post("/api/auth/logout")

    # The client comes back with the "stolen" cookie after logout.
    r = await client.get("/api/auth/me", headers={"Cookie": f"session={stolen}"})
    assert r.status_code == 401, "Stolen cookie still valid after logout"


@pytest.mark.asyncio
async def test_locked_account_rejects_active_session(client, session):
    """Account lockout (`user.locked_until` in the future) must also end
    active cookie sessions; otherwise an attacker who already holds the
    cookie carries on despite the lock. Regression test for CWE-613.

    We simulate the lockout by setting `locked_until` in the database
    instead of a real brute force, because the login rate limit (5/15min)
    fires before lockout_threshold (10) in the current configuration."""
    from datetime import UTC, datetime, timedelta

    user = await mk_user(session)
    await session.commit()
    await _login(client, user)
    stolen = client.cookies.get("session")
    assert (
        await client.get("/api/auth/me", headers={"Cookie": f"session={stolen}"})
    ).status_code == 200

    # Lock the account directly in the DB.
    user.locked_until = datetime.now(UTC) + timedelta(minutes=15)
    await session.commit()

    # The cookie is still cryptographically valid, but get_current_user sees
    # locked_until > now -> revoke sid + 403.
    r = await client.get("/api/auth/me", headers={"Cookie": f"session={stolen}"})
    assert r.status_code == 403, "Lockout did not end the active session (CWE-613)"

    # The next request with the same cookie -> 401 (sid revoked after the first rejection).
    r2 = await client.get("/api/auth/me", headers={"Cookie": f"session={stolen}"})
    assert r2.status_code == 401, "Sid should be revoked after the lockout check"


@pytest.mark.asyncio
async def test_session_revocation_via_logout_blocks_all_endpoints(client, session):
    """Logout must invalidate the session for every endpoint, not only
    /me. Checks that after logout a stolen cookie also fails on an
    endpoint that does not call get_current_user directly (e.g.
    OAuth /authorize)."""
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)
    stolen = client.cookies.get("session")

    # /api/auth/me (smoke check first that the cookie works).
    assert (
        await client.get("/api/auth/me", headers={"Cookie": f"session={stolen}"})
    ).status_code == 200

    await client.post("/api/auth/logout")

    # /api/auth/me: 401 (revoked sid).
    r1 = await client.get("/api/auth/me", headers={"Cookie": f"session={stolen}"})
    assert r1.status_code == 401

    # OAuth /authorize: no sid in the session -> redirect to login (302).
    # This route checks differently from get_current_user, but uses the same
    # session_store.is_revoked, so it must reject too.
    r2 = await client.get(
        "/api/auth/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": "ics-mcp-stdio",
            "redirect_uri": "http://localhost:9000/cb",
            "scope": "ics",
            "code_challenge": "x" * 43,
            "code_challenge_method": "S256",
            "resource": "https://ics.test/mcp",
        },
        headers={"Cookie": f"session={stolen}"},
        follow_redirects=False,
    )
    # Redirect to the frontend login (Starlette RedirectResponse defaults
    # to 307). Key point: not 200 (consent HTML), and Location points to the frontend.
    assert r2.status_code in (302, 303, 307), (
        f"OAuth /authorize ignores revocation: {r2.status_code}"
    )
    route, _, query = urlsplit(r2.headers["location"]).fragment.partition("?")
    assert route == "login", "redirect without the login route suggests session acceptance"
    original = urlsplit(str(r2.request.url))
    assert parse_qs(query) == {"next": [f"{original.path}?{original.query}"]}


# ---------- /password-reset ----------


@pytest.mark.asyncio
async def test_password_reset_request_returns_200_for_unknown_email(client):
    """Anti-enumeration: 200 even for a nonexistent email."""
    r = await client.post(
        "/api/auth/password-reset/request",
        json={"email": _uniq_email("phantom")},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True}


@pytest.mark.asyncio
async def test_password_reset_confirm_changes_password(client, session):
    user = await mk_user(session, password="OldPass1!")
    await session.commit()
    token = tokens.issue("reset", str(user.id))

    r = await client.post(
        "/api/auth/password-reset/confirm",
        json={"token": token, "new_password": "BrandNewPass2!"},
    )
    assert r.status_code == 200

    # The old password no longer works.
    bad = await client.post("/api/auth/login", json=_login_payload(user.email, "OldPass1!"))
    assert bad.status_code == 401
    # The new one works.
    good = await client.post(
        "/api/auth/login",
        json=_login_payload(user.email, "BrandNewPass2!"),
    )
    assert good.status_code == 200


@pytest.mark.asyncio
async def test_password_reset_confirm_keeps_admin_lock_and_clears_lockout(client, session):
    """A new password ends a failed-attempt lockout but not an administrator's lock."""
    from datetime import UTC, datetime, timedelta

    from app import audit

    admin = await mk_admin(session)
    locked = await mk_user(session, password="OldPass1!")
    lockout = await mk_user(session, password="OldPass1!")
    until = datetime.now(UTC) + timedelta(hours=1)
    locked.locked_until = until
    lockout.locked_until = until
    await audit.record(
        session, actor=admin, action="user_locked_by_admin", target=f"user:{locked.id}"
    )
    await audit.record(session, actor=None, action="account_locked", target=f"user:{lockout.id}")
    await session.commit()

    for user in (locked, lockout):
        r = await client.post(
            "/api/auth/password-reset/confirm",
            json={"token": tokens.issue("reset", str(user.id)), "new_password": "BrandNewPass2!"},
        )
        assert r.status_code == 200
    await session.refresh(locked)
    await session.refresh(lockout)
    assert locked.locked_until == until
    assert lockout.locked_until is None


@pytest.mark.asyncio
async def test_password_reset_confirm_rejects_bad_token(client):
    r = await client.post(
        "/api/auth/password-reset/confirm",
        json={"token": "obviously-not-a-real-token", "new_password": "ValidPass12!"},
    )
    assert r.status_code == 400


# ---------- /invite + /setup ----------


@pytest.mark.asyncio
async def test_invite_requires_admin(client, session):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    r = await client.post(
        "/api/auth/invite",
        json={"email": "newbie@example.com", "role": "user"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_invite_creates_inactive_user_and_setup_flow_activates(client, session):
    admin = await mk_admin(session)
    await session.commit()
    await _login(client, admin)

    invitee_email = _uniq_email("invited")
    r = await client.post(
        "/api/auth/invite",
        json={"email": invitee_email, "role": "user"},
    )
    assert r.status_code == 201
    payload = r.json()
    assert payload["email"] == invitee_email
    assert payload["role"] == "user"

    # The user exists in the database but is "inactive" (no password_hash, not verified).
    invited = (await session.execute(select(User).where(User.email == invitee_email))).scalar_one()
    assert invited.password_hash is None
    assert invited.email_verified_at is None
    assert invited.auth_method == "invite"

    # The token normally comes from the URL in the email; here we issue it directly.
    setup_token = tokens.issue("invite", str(invited.id))
    setup = await client.post(
        "/api/auth/setup",
        json={"token": setup_token, "password": "BrandNewPass123!", "display_name": "Fresh"},
    )
    assert setup.status_code == 200

    await session.refresh(invited)
    assert invited.password_hash is not None
    assert invited.email_verified_at is not None
    assert invited.display_name == "Fresh"
    assert invited.auth_method == "password"


@pytest.mark.asyncio
async def test_invite_conflict_when_user_exists(client, session):
    admin = await mk_admin(session)
    target = await mk_user(session, email=_uniq_email("collision"))
    await session.commit()
    await _login(client, admin)

    r = await client.post(
        "/api/auth/invite",
        json={"email": target.email, "role": "user"},
    )
    assert r.status_code == 409


# ---------- /register ----------


@pytest.mark.asyncio
async def test_register_returns_403_when_self_register_disabled(client):
    """Default settings -> 403 (ICS_ALLOW_SELF_REGISTER=false)."""
    r = await client.post(
        "/api/auth/register",
        json={"email": _uniq_email("stranger"), "password": "FreshPass123!"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_register_creates_user_when_self_register_enabled(client, session, monkeypatch):
    """With `allow_self_register=true` a user from an allowed domain creates
    an account. Returns 201 with `{"ok": True}` (anti-enumeration)."""
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "allow_self_register", True)

    email = _uniq_email("new")
    r = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "Strong-Pass-123!"},
    )
    assert r.status_code == 201
    assert r.json() == {"ok": True}

    # The user was created in the DB with `email_verified_at=None`.
    user = (await session.execute(select(User).where(User.email == email))).scalar_one()
    assert user.password_hash is not None
    assert user.email_verified_at is None


@pytest.mark.asyncio
async def test_register_silently_succeeds_for_existing_email(client, session, monkeypatch):
    """Anti-enumeration: re-registering an existing email -> 201 ok with no
    changes. The backend never reveals that the email exists."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "allow_self_register", True)
    user = await mk_user(session)
    await session.commit()

    r = await client.post(
        "/api/auth/register",
        json={"email": user.email, "password": "Different-Pass-1!"},
    )
    assert r.status_code == 201
    # The user still has the original password; register did not change it.
    await session.refresh(user)
    assert passwords.verify_password("TestPass123!", user.password_hash)


@pytest.mark.asyncio
async def test_register_rejects_weak_password(client, monkeypatch):
    """Pydantic min_length blocks a weak password before it reaches the
    self-register gate."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "allow_self_register", True)
    r = await client.post(
        "/api/auth/register",
        json={"email": _uniq_email("x"), "password": "weak"},
    )
    assert r.status_code == 422


# ---------- /verify ----------


@pytest.mark.asyncio
async def test_verify_marks_email_as_verified(client, session):
    user = await mk_user(session, email_verified=False)
    await session.commit()
    assert user.email_verified_at is None

    token = tokens.issue("verify", str(user.id))
    r = await client.post(f"/api/auth/verify?token={token}")
    assert r.status_code == 200

    await session.refresh(user)
    assert user.email_verified_at is not None


@pytest.mark.asyncio
async def test_verify_rejects_invalid_token(client):
    r = await client.post("/api/auth/verify?token=not-a-real-token")
    assert r.status_code == 400


# ---------- /google/login ----------


@pytest.mark.asyncio
async def test_google_login_returns_503_when_oidc_not_configured(client, monkeypatch):
    """Without `ICS_GOOGLE_OIDC_CLIENT_ID` -> 503. Guards that the
    `require_google_oidc` dependency really refuses when there are no keys.

    We force an empty client_id via monkeypatch; otherwise the test depends
    on env (dev/CI with OIDC configured returns 302 instead of 503).
    """
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "google_oidc_client_id", "")
    r = await client.get("/api/auth/google/login", follow_redirects=False)
    assert r.status_code == 503


# ---------- security: rate limiting ----------


@pytest.mark.asyncio
async def test_login_rate_limit_returns_429_with_retry_after(client, session):
    """A rate-limit hit must be visible to the client: 429 + Retry-After.
    A silent 401 would be indistinguishable from bad credentials and hide
    the throttling."""
    fake_email = _uniq_email("ratelimit")
    saw_429 = False
    for _ in range(30):
        r = await client.post(
            "/api/auth/login",
            json=_login_payload(fake_email, "WhateverPass1!"),
        )
        # Before the limit kicks in: 401 (bad credentials). After: 429 + Retry-After.
        assert r.status_code in (401, 429)
        if r.status_code == 429:
            saw_429 = True
            assert r.headers.get("Retry-After"), "429 must carry Retry-After"
            retry_after = int(r.headers["Retry-After"])
            assert 1 <= retry_after <= 15 * 60  # bound by LOGIN window
            break
    assert saw_429, "rate limit should return 429 after ~5 attempts"


@pytest.mark.asyncio
async def test_password_reset_rate_limit_returns_429(client):
    """Anti-enumeration is kept (the plain 200 does not depend on whether
    the email exists), but a rate-limit hit must return 429 + Retry-After
    so a legitimate client and the operator see the throttling. The rate
    limit does not depend on the account existing, so it enables no enumeration."""
    saw_429 = False
    for i in range(15):
        r = await client.post(
            "/api/auth/password-reset/request",
            json={"email": f"reset-rl-{i}@example.com"},
        )
        assert r.status_code in (200, 429)
        if r.status_code == 429:
            saw_429 = True
            assert r.headers.get("Retry-After")
            break
    assert saw_429


# ---------- password validation ----------


@pytest.mark.asyncio
async def test_password_reset_confirm_rejects_weak_password(client, session):
    user = await mk_user(session)
    await session.commit()
    token = tokens.issue("reset", str(user.id))

    r = await client.post(
        "/api/auth/password-reset/confirm",
        json={"token": token, "new_password": "weak"},
    )
    # Pydantic rejects it (min_length=passwords.MIN_LENGTH) before business
    # validation runs: 422. We accept 400 and 422 (both mean "rejected").
    assert r.status_code in (400, 422)
    # The password really was not changed.
    await session.refresh(user)
    assert passwords.verify_password("TestPass123!", user.password_hash)
