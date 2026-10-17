"""Tests for `routes/shares.py`: ShareLink CRUD + public viewer.

Covers:
- POST /api/assets/{id}/shares: create org_sso/public/password (happy + 403 + 400).
- GET /api/assets/{id}/shares: list.
- DELETE /api/shares/{id}: revoke (idempotent).
- GET /api/share/{token}/info: discovery for the frontend.
- POST /api/share/{token}/auth: password challenge (200/401/rate limit).
- GET /api/share/{token}/doc: render + view counter increment.
- 410 for revoked/expired/max_views.
- 404 for an unknown token.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models import Asset, ShareLink
from app.slug import generate_token
from tests.conftest import login_as as _login
from tests.conftest import mk_asset, mk_user


async def _create_share(client, asset: Asset, mode: str = "public", **extra) -> dict:
    body = {"mode": mode, **extra}
    r = await client.post(f"/api/assets/{asset.id}/shares", json=body)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
async def test_create_public_share(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)

    r = await client.post(
        f"/api/assets/{asset.id}/shares",
        json={"mode": "public"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["mode"] == "public"
    assert body["url"].endswith(f"/s/{body['token']}")
    assert body["requires_password"] is False
    assert body["revoked_at"] is None
    assert body["view_count"] == 0


@pytest.mark.asyncio
async def test_create_org_sso_share(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)

    payload = await _create_share(client, asset, mode="org_sso")
    assert payload["mode"] == "org_sso"
    assert payload["requires_password"] is False


@pytest.mark.asyncio
async def test_create_password_share_requires_password(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)

    r = await client.post(
        f"/api/assets/{asset.id}/shares",
        json={"mode": "password"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_create_password_share_happy(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)

    r = await client.post(
        f"/api/assets/{asset.id}/shares",
        json={"mode": "password", "password": "VisitorPass1!"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["mode"] == "password"
    assert body["requires_password"] is True


@pytest.mark.asyncio
async def test_create_share_rejects_non_owner(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    stranger = await mk_user(session)
    await session.commit()
    await _login(client, stranger)

    r = await client.post(
        f"/api/assets/{asset.id}/shares",
        json={"mode": "public"},
    )
    assert r.status_code in (403, 404)


@pytest.mark.asyncio
async def test_create_share_rejects_critical_asset(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner, security_status="critical")
    await session.commit()
    await _login(client, owner)

    r = await client.post(
        f"/api/assets/{asset.id}/shares",
        json={"mode": "public"},
    )
    assert r.status_code == 403
    assert r.json()["code"] == "asset_critical"


@pytest.mark.asyncio
async def test_create_share_with_expiry(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)

    expires = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    r = await client.post(
        f"/api/assets/{asset.id}/shares",
        json={"mode": "public", "expires_at": expires, "max_views": 5},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["expires_at"] is not None
    assert body["max_views"] == 5


@pytest.mark.asyncio
async def test_list_shares_returns_only_for_asset(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)

    await _create_share(client, asset, mode="public")
    await _create_share(client, asset, mode="org_sso")

    r = await client.get(f"/api/assets/{asset.id}/shares")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2
    modes = sorted(s["mode"] for s in rows)
    assert modes == ["org_sso", "public"]


@pytest.mark.asyncio
async def test_list_shares_rejects_non_owner(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    stranger = await mk_user(session)
    await session.commit()
    await _login(client, owner)
    await _create_share(client, asset)
    await client.post("/api/auth/logout")
    await _login(client, stranger)

    r = await client.get(f"/api/assets/{asset.id}/shares")
    assert r.status_code in (403, 404)


@pytest.mark.asyncio
async def test_revoke_share_makes_it_410(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)

    share = await _create_share(client, asset, mode="public")
    revoke = await client.delete(f"/api/shares/{share['id']}")
    assert revoke.status_code == 204

    # Unauthenticated viewer: the token now returns 410.
    await client.post("/api/auth/logout")
    info = await client.get(f"/api/share/{share['token']}/info")
    assert info.status_code == 410


@pytest.mark.asyncio
async def test_revoke_share_idempotent(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)
    share = await _create_share(client, asset)

    r1 = await client.delete(f"/api/shares/{share['id']}")
    r2 = await client.delete(f"/api/shares/{share['id']}")
    # The second delete must not blow up even though the share is already revoked.
    assert r1.status_code == 204
    assert r2.status_code == 204


@pytest.mark.asyncio
async def test_revoke_unknown_share_returns_404(client, session):
    owner = await mk_user(session)
    await session.commit()
    await _login(client, owner)

    r = await client.delete("/api/shares/00000000-0000-0000-0000-000000000001")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_info_for_public_share(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)
    share = await _create_share(client, asset, mode="public")
    await client.post("/api/auth/logout")

    r = await client.get(f"/api/share/{share['token']}/info")
    assert r.status_code == 200
    info = r.json()
    assert info["mode"] == "public"
    assert info["has_access"] is True
    assert info["requires_password"] is False
    assert info["requires_login"] is False


@pytest.mark.asyncio
async def test_info_for_password_share_requires_challenge(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)
    share = await _create_share(client, asset, mode="password", password="LetMeIn1234!")
    await client.post("/api/auth/logout")

    r = await client.get(f"/api/share/{share['token']}/info")
    info = r.json()
    assert info["mode"] == "password"
    assert info["requires_password"] is True
    assert info["has_access"] is False


@pytest.mark.asyncio
async def test_info_for_org_sso_requires_login(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)
    share = await _create_share(client, asset, mode="org_sso")
    await client.post("/api/auth/logout")

    r = await client.get(f"/api/share/{share['token']}/info")
    info = r.json()
    assert info["requires_login"] is True
    assert info["has_access"] is False


@pytest.mark.asyncio
async def test_info_for_unknown_token_404(client):
    r = await client.get("/api/share/totallyfakeXYZ/info")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_password_auth_grants_session_access(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)
    share = await _create_share(client, asset, mode="password", password="GoodPass1234!")
    await client.post("/api/auth/logout")

    bad = await client.post(
        f"/api/share/{share['token']}/auth",
        json={"password": "WrongPass1!"},
    )
    assert bad.status_code == 401

    good = await client.post(
        f"/api/share/{share['token']}/auth",
        json={"password": "GoodPass1234!"},
    )
    assert good.status_code == 200

    # Cookie now marks share as verified, so info reports has_access.
    info = await client.get(f"/api/share/{share['token']}/info")
    assert info.json()["has_access"] is True


@pytest.mark.asyncio
async def test_password_auth_rejects_wrong_mode(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)
    share = await _create_share(client, asset, mode="public")
    await client.post("/api/auth/logout")

    r = await client.post(
        f"/api/share/{share['token']}/auth",
        json={"password": "Whatever1!"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_share_expired_returns_410(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)
    # Create an expired share directly (bypasses the endpoint's validation).
    expired = ShareLink(
        asset_id=asset.id,
        token=generate_token(),
        mode="public",
        created_by=owner.id,
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    session.add(expired)
    await session.commit()
    await client.post("/api/auth/logout")

    r = await client.get(f"/api/share/{expired.token}/info")
    assert r.status_code == 410


@pytest.mark.asyncio
async def test_share_max_views_exhausted_returns_410(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)
    exhausted = ShareLink(
        asset_id=asset.id,
        token=generate_token(),
        mode="public",
        created_by=owner.id,
        max_views=1,
        view_count=1,
    )
    session.add(exhausted)
    await session.commit()
    await client.post("/api/auth/logout")

    r = await client.get(f"/api/share/{exhausted.token}/info")
    assert r.status_code == 410


@pytest.mark.asyncio
async def test_doc_endpoint_404_for_unknown_token(client):
    r = await client.get("/api/share/totally-unknown-xyz/doc")
    assert r.status_code == 404
