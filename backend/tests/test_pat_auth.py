"""Authentication with personal access tokens (ADR-0020): the bearer 401
contract, the account lock, and no admin powers for a PAT request."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.auth import require_admin
from app.services import pat
from tests.conftest import mk_admin, mk_asset, mk_user


def _in_days(days: float) -> datetime:
    return datetime.now(UTC) + timedelta(days=days)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _token(session, user, days: float = 30) -> str:
    _, plaintext = await pat.create(session, user=user, name="ps", expires_at=_in_days(days))
    await session.commit()
    return plaintext


async def test_valid_pat_authenticates_and_records_use(client, session):
    user = await mk_user(session)
    token = await _token(session, user)

    r = await client.get("/api/auth/me", headers=_bearer(token))
    assert r.status_code == 200
    assert r.json()["id"] == str(user.id)

    row = await pat.verify(session, token)
    assert row is not None
    await session.refresh(row)
    assert row.last_used_at is not None


async def test_admin_pat_is_evaluated_as_an_ordinary_user(client, session):
    admin = await mk_admin(session)
    stranger = await mk_user(session)
    hidden = await mk_asset(session, stranger, title="Not for the admin token")
    token = await _token(session, admin)

    r = await client.get(f"/api/assets/{hidden.id}", headers=_bearer(token))
    assert r.status_code == 404
    r = await client.get(f"/api/assets/by-slug/{hidden.slug}/relations", headers=_bearer(token))
    assert r.status_code == 404
    r = await client.get("/api/assets/index", headers=_bearer(token))
    assert r.status_code == 200
    assert hidden.slug not in r.text


async def test_admin_routes_refuse_pat(client, session):
    admin = await mk_admin(session)
    token = await _token(session, admin)

    for path in ("/api/admin/audit/actions", "/api/admin/users", "/api/admin/doc-types"):
        r = await client.get(path, headers=_bearer(token))
        assert r.status_code == 403, path
        assert r.json()["code"] == "admin_required"


def _depends_on(dependant, target) -> bool:
    return any(d.call is target or _depends_on(d, target) for d in dependant.dependencies)


async def test_every_admin_route_requires_admin():
    from fastapi.routing import APIRoute

    from app.main import create_app
    from app.routes import admin, admin_users, doc_types

    routes = [
        r
        for router in (admin.router, admin_users.router, doc_types.admin_router)
        for r in router.routes
        if isinstance(r, APIRoute)
    ]
    # The walked routers must cover every /api/admin path the app serves.
    served = {p for p in create_app().openapi()["paths"] if p.startswith("/api/admin")}
    assert served and served <= {r.path for r in routes}
    missing = [r.path for r in routes if not _depends_on(r.dependant, require_admin)]
    assert missing == []


async def test_bad_or_expired_pat_gets_bearer_401(client, session):
    user = await mk_user(session)
    good = await _token(session, user)
    row, expired = await pat.create(session, user=user, name="old", expires_at=_in_days(1))
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.commit()

    for token in (
        expired,
        good[:-4] + "xxxx",
        "ics_pat_notahex_secret",
        "ics_pat_",
    ):
        r = await client.get("/api/auth/me", headers=_bearer(token))
        assert r.status_code == 401, token
        assert r.json()["code"] == "invalid_token"
        assert r.headers["www-authenticate"].startswith("Bearer ")


async def test_revoked_pat_gets_bearer_401(client, session):
    user = await mk_user(session)
    row, token = await pat.create(session, user=user, name="ps", expires_at=_in_days(30))
    await pat.revoke(session, token_id=row.id, user_id=user.id, actor=user)
    await session.commit()

    r = await client.get("/api/auth/me", headers=_bearer(token))
    assert r.status_code == 401
    assert "www-authenticate" in r.headers


async def test_locked_account_cannot_use_pat(client, session):
    user = await mk_user(session)
    token = await _token(session, user)
    user.locked_until = datetime.now(UTC) + timedelta(hours=1)
    await session.commit()

    r = await client.get("/api/auth/me", headers=_bearer(token))
    assert r.status_code == 403
    assert r.json()["code"] == "account_locked"


async def test_pat_request_carries_pat_transport_for_audit(client, session):
    user = await mk_user(session)
    token = await _token(session, user)

    r = await client.get("/api/auth/oauth/me", headers=_bearer(token))
    assert r.status_code == 200
    assert r.json()["transport"] == "pat"
    assert r.json()["scopes"] == ["ics:read"]
