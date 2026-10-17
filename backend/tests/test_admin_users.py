"""Admin user-management endpoints: permission gate, audit trail,
guardrails (last-admin protection, self-lock protection)."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db import Base
from app.errors import ApiError
from app.models import Asset, AuditLog, User
from app.routes.admin_users import (
    InviteIn,
    LockIn,
    PatchUserIn,
    admin_password_reset,
    delete_user,
    invite_user,
    list_users,
    lock_user,
    patch_user,
    reinvite,
    unlock_user,
)
from app.slug import generate_slug


@pytest_asyncio.fixture
async def session():
    settings = get_settings()
    engine = create_async_engine(settings.database_url, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _mk_user(session, *, role: str = "user", email: str | None = None) -> User:
    u = User(
        email=email or f"u+{generate_slug(6)}@example.com",
        role=role,
        auth_method="password",
        display_name=f"User {generate_slug(4)}",
    )
    session.add(u)
    await session.flush()
    return u


# ---------- list / summary ----------


@pytest.mark.asyncio
async def test_list_returns_summary_and_users(session):
    admin = await _mk_user(session, role="admin")
    await _mk_user(session)
    await session.commit()

    out = await list_users(
        admin,
        session,
        q=None,
        role=None,
        status_filter=None,
        page=1,
        page_size=200,
    )
    assert "summary" in out and "users" in out
    assert out["summary"]["total"] >= 2
    assert out["summary"]["admins"] >= 1
    assert all("email" in u for u in out["users"])
    assert out["total"] >= 2


@pytest.mark.asyncio
async def test_list_filters_by_role(session):
    admin = await _mk_user(session, role="admin")
    await _mk_user(session, role="user")
    await session.commit()

    only_admins = await list_users(
        admin,
        session,
        q=None,
        role="admin",
        status_filter=None,
        page=1,
        page_size=200,
    )
    assert all(u["role"] == "admin" for u in only_admins["users"])


@pytest.mark.asyncio
async def test_list_search_matches_email_substring(session):
    admin = await _mk_user(session, role="admin")
    target = await _mk_user(session, email=f"unique-{generate_slug(8)}@example.com")
    await session.commit()

    out = await list_users(
        admin,
        session,
        q=target.email[:15],
        role=None,
        status_filter=None,
        page=1,
        page_size=200,
    )
    emails = [u["email"] for u in out["users"]]
    assert target.email in emails


# ---------- invite ----------


@pytest.mark.asyncio
async def test_invite_creates_user_and_audit(session):
    admin = await _mk_user(session, role="admin")
    settings = get_settings()
    body = InviteIn(email=f"new-{generate_slug(6)}@example.com", role="user")

    out = await invite_user(body, admin, session, settings)

    assert out["email"] == body.email
    assert out["email_verified"] is False  # invite-only; user hasn't set password

    audits = (
        (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.action == "user_invited",
                    AuditLog.target == f"user:{out['id']}",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audits) == 1


@pytest.mark.asyncio
async def test_invite_rejects_duplicate(session):
    admin = await _mk_user(session, role="admin")
    existing = await _mk_user(session)
    await session.commit()
    settings = get_settings()

    with pytest.raises(HTTPException) as exc:
        await invite_user(InviteIn(email=existing.email), admin, session, settings)
    assert exc.value.status_code == 409


# ---------- patch (role / quota / display_name) ----------


@pytest.mark.asyncio
async def test_patch_changes_role_with_audit(session):
    admin = await _mk_user(session, role="admin")
    user = await _mk_user(session, role="user")
    await session.commit()

    out = await patch_user(user.id, PatchUserIn(role="external"), admin, session)
    assert out["role"] == "external"

    audits = (
        (await session.execute(select(AuditLog).where(AuditLog.action == "user_role_changed")))
        .scalars()
        .all()
    )
    assert any(a.target == f"user:{user.id}" for a in audits)


@pytest.mark.asyncio
async def test_patch_refuses_to_demote_last_admin(session):
    """If only one admin remains, demoting them locks the org out of
    admin-only flows. Guardrail blocks the action."""
    admin = await _mk_user(session, role="admin")
    await session.commit()
    # Admins created by other tests in the shared DB would let the demotion
    # succeed, so the guardrail can only be checked when this one is alone.
    cnt = (
        await session.execute(
            select(__import__("sqlalchemy").func.count(User.id)).where(User.role == "admin")
        )
    ).scalar_one()
    if cnt > 1:
        pytest.skip("DB has other admins from prior tests, guardrail not triggered")
    with pytest.raises(ApiError) as exc:
        await patch_user(admin.id, PatchUserIn(role="user"), admin, session)
    assert exc.value.status_code == 400
    assert exc.value.code == "last_admin"


@pytest.mark.asyncio
async def test_patch_quota_audited(session):
    admin = await _mk_user(session, role="admin")
    user = await _mk_user(session)
    await session.commit()

    out = await patch_user(user.id, PatchUserIn(storage_quota_bytes=2 * 1024**3), admin, session)
    assert out["storage_quota_bytes"] == 2 * 1024**3


@pytest.mark.asyncio
async def test_patch_bundle_limit_audited(session):
    admin = await _mk_user(session, role="admin")
    user = await _mk_user(session)
    await session.commit()

    out = await patch_user(user.id, PatchUserIn(bundle_max_bytes=20 * 1024**2), admin, session)
    assert out["bundle_max_bytes"] == 20 * 1024**2


@pytest.mark.asyncio
async def test_patch_html_autobypass_audited(session):
    admin = await _mk_user(session, role="admin")
    user = await _mk_user(session)
    await session.commit()

    out = await patch_user(user.id, PatchUserIn(html_autobypass=True), admin, session)
    assert out["html_autobypass"] is True


# ---------- lock / unlock ----------


@pytest.mark.asyncio
async def test_lock_sets_until_and_audits(session):
    admin = await _mk_user(session, role="admin")
    user = await _mk_user(session)
    await session.commit()

    out = await lock_user(user.id, LockIn(minutes=30, reason="test"), admin, session)
    assert out["locked_until"] is not None
    await session.refresh(user)
    assert user.locked_until is not None and user.locked_until > datetime.now(UTC)


@pytest.mark.asyncio
async def test_lock_refuses_self(session):
    admin = await _mk_user(session, role="admin")
    await session.commit()
    with pytest.raises(HTTPException) as exc:
        await lock_user(admin.id, LockIn(minutes=15), admin, session)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_unlock_clears_locked_until(session):
    admin = await _mk_user(session, role="admin")
    user = await _mk_user(session)
    user.locked_until = datetime.now(UTC) + timedelta(minutes=15)
    await session.commit()
    await unlock_user(user.id, admin, session)
    await session.refresh(user)
    assert user.locked_until is None


# ---------- password reset / reinvite ----------


@pytest.mark.asyncio
async def test_password_reset_only_for_password_auth(session):
    admin = await _mk_user(session, role="admin")
    sso_user = User(
        email=f"sso-{generate_slug(6)}@example.com",
        role="user",
        auth_method="google_sso",
    )
    session.add(sso_user)
    await session.commit()
    settings = get_settings()
    with pytest.raises(HTTPException) as exc:
        await admin_password_reset(sso_user.id, admin, session, settings)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_reinvite_only_for_unverified(session):
    admin = await _mk_user(session, role="admin")
    verified = await _mk_user(session)
    verified.email_verified_at = datetime.now(UTC)
    await session.commit()
    settings = get_settings()
    with pytest.raises(HTTPException) as exc:
        await reinvite(verified.id, admin, session, settings)
    assert exc.value.status_code == 400


# ---------- delete ----------


@pytest.mark.asyncio
async def test_delete_cascades_assets_and_returns_count(session):
    admin = await _mk_user(session, role="admin")
    victim = await _mk_user(session)
    session.add(
        Asset(
            id=uuid4(),
            slug=generate_slug(),
            owner_id=victim.id,
            kind="md_single",
            title="t",
            storage_prefix="x",
            entry_path="x.md",
            security_status="clean",
            version=1,
            size_bytes=10,
        )
    )
    await session.commit()

    out = await delete_user(victim.id, admin, session)
    assert out["deleted"] is True
    assert out["cascade_assets"] == 1


@pytest.mark.asyncio
async def test_delete_refuses_self(session):
    admin = await _mk_user(session, role="admin")
    await session.commit()
    with pytest.raises(HTTPException) as exc:
        await delete_user(admin.id, admin, session)
    assert exc.value.status_code == 400
