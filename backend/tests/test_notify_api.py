"""Notifications API (docs/notifications-api.md): inbox, preferences, push
devices, e-mail opt-out and watches."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app import tokens
from app.config import get_settings
from app.models import AssetShare, NotificationPreference
from app.redis_client import get_redis
from app.services.notifications import inbox
from app.services.notifications.channels import vapid
from app.services.notifications.inbox import Delivery
from tests.conftest import login_as, mk_asset, mk_user

_WEBHOOK = "https://chat.googleapis.com/v1/spaces/AAQ123/messages?key=k&token=t"
_FCM = "https://fcm.googleapis.com/fcm/send/abc123"
_KEYS = {"p256dh": "B" * 87, "auth": "a" * 22}


async def _seed(user_id, asset, n: int = 1) -> list[str]:
    payload = {
        "c": "asset.updated",
        "as": str(asset.id),
        "sl": asset.slug,
        "t": asset.title,
        "k": asset.kind,
        "v": 2,
        "n": 1,
    }
    results = await inbox.push_many(
        get_redis(), [Delivery(user_id, dict(payload)) for _ in range(n)], get_settings()
    )
    return [r[0] for r in results]


async def test_list_read_delete_and_access_recheck(client: AsyncClient, session: AsyncSession):
    owner = await mk_user(session)
    reader = await mk_user(session)
    asset = await mk_asset(session, owner, title="Spec")
    share = AssetShare(asset_id=asset.id, user_id=reader.id, role="viewer")
    session.add(share)
    await session.commit()
    ids = await _seed(reader.id, asset, 2)
    await login_as(client, reader)

    r = await client.get("/api/notifications")
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 2 and "unread" not in body
    item = body["items"][0]
    assert item["asset"]["title"] == "Spec" and item["link"] == f"/v/{asset.slug}"
    assert item["unavailable"] is False

    r = await client.post("/api/notifications/read", json={"ids": [ids[0]]})
    assert r.json() == {"unread": 1}
    assert (await client.get("/api/notifications/summary")).json() == {"unread": 1}
    assert (await client.delete(f"/api/notifications/{ids[0]}")).json() == {"unread": 1}
    r = await client.delete(f"/api/notifications/{ids[0]}")
    assert r.status_code == 404 and r.json()["code"] == "notification_not_found"

    await session.delete(share)
    await session.commit()
    item = (await client.get("/api/notifications")).json()["items"][0]
    assert item["unavailable"] is True and item["asset"] is None and item["link"] is None

    assert (await client.post("/api/notifications/read", json={"all": True})).json() == {
        "unread": 0
    }
    assert (await client.delete("/api/notifications")).json() == {"unread": 0}
    assert (await client.get("/api/notifications")).json()["items"] == []


async def test_bad_cursor_is_rejected(client: AsyncClient, session: AsyncSession):
    user = await mk_user(session)
    await login_as(client, user)
    r = await client.get("/api/notifications", params={"before": "-"})
    assert r.status_code == 400 and r.json()["code"] == "invalid_cursor"


async def test_preferences_defaults_and_updates(client: AsyncClient, session: AsyncSession):
    user = await mk_user(session)
    await login_as(client, user)
    prefs = (await client.get("/api/notifications/preferences")).json()
    assert prefs["enabled"] is True and prefs["email_mode"] == "off"
    assert "email" in prefs["events"]["asset.updated"]
    assert prefs["chat"]["configured"] is False

    r = await client.put(
        "/api/notifications/preferences",
        json={"email_mode": "daily", "events": {"asset.updated": ["push"]}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["email_mode"] == "daily" and body["events"]["asset.updated"] == ["push"]
    assert body["events"]["asset.created"] == prefs["events"]["asset.created"]


async def test_chat_webhook_is_validated_encrypted_and_removable(
    client: AsyncClient, session: AsyncSession
):
    user = await mk_user(session)
    await login_as(client, user)
    r = await client.put(
        "/api/notifications/preferences",
        json={"chat_webhook_url": "https://evil.example/v1/spaces/X/messages"},
    )
    assert r.status_code == 400 and r.json()["code"] == "invalid_webhook_url"

    r = await client.put("/api/notifications/preferences", json={"chat_webhook_url": _WEBHOOK})
    chat = r.json()["chat"]
    assert chat == {"configured": True, "space": "AAQ123", "enabled": True, "error_code": None}
    row = await session.get(NotificationPreference, user.id)
    await session.refresh(row)
    assert row is not None and row.chat_webhook_enc and _WEBHOOK not in row.chat_webhook_enc

    r = await client.put("/api/notifications/preferences", json={"chat_webhook_url": None})
    assert r.json()["chat"]["configured"] is False
    r = await client.put("/api/notifications/preferences", json={"chat_enabled": True})
    assert r.status_code == 400 and r.json()["code"] == "chat_not_configured"


async def test_push_devices(client: AsyncClient, session: AsyncSession, monkeypatch):
    user = await mk_user(session)
    await login_as(client, user)
    body = {"endpoint": _FCM, "keys": _KEYS, "label": "Brave on macOS"}
    r = await client.put("/api/notifications/push/subscriptions", json=body)
    assert r.status_code == 409 and r.json()["code"] == "push_not_configured"

    settings = get_settings()
    private, public = vapid.generate()
    monkeypatch.setattr(settings, "vapid_private_key", private)
    monkeypatch.setattr(settings, "vapid_subject", "mailto:ops@example.com")
    assert (await client.get("/api/notifications/preferences")).json()["push"] == {
        "available": True,
        "public_key": public,
    }
    r = await client.put(
        "/api/notifications/push/subscriptions",
        json={**body, "endpoint": "https://10.0.0.5/push"},
    )
    assert r.status_code == 400 and r.json()["code"] == "push_endpoint_not_allowed"

    r = await client.put("/api/notifications/push/subscriptions", json=body)
    device_id = r.json()["id"]
    again = await client.put("/api/notifications/push/subscriptions", json=body)
    assert again.json()["id"] == device_id
    items = (await client.get("/api/notifications/push/subscriptions")).json()["items"]
    assert [i["label"] for i in items] == ["Brave on macOS"]
    r = await client.delete(f"/api/notifications/push/subscriptions/{device_id}")
    assert r.status_code == 204
    r = await client.delete(f"/api/notifications/push/subscriptions/{device_id}")
    assert r.status_code == 404 and r.json()["code"] == "push_subscription_not_found"


async def test_one_click_unsubscribe_needs_no_login(client: AsyncClient, session: AsyncSession):
    user = await mk_user(session)
    session.add(NotificationPreference(user_id=user.id, email_mode="batched", events={}))
    await session.commit()
    token = tokens.issue("notify_unsubscribe", str(user.id))
    r = await client.post(
        "/api/notifications/unsubscribe",
        params={"token": token},
        content="List-Unsubscribe=One-Click",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 204
    row = await session.get(NotificationPreference, user.id)
    await session.refresh(row)
    assert row is not None and row.email_mode == "off"
    r = await client.post("/api/notifications/unsubscribe", json={"token": "forged"})
    assert r.status_code == 400 and r.json()["code"] == "invalid_unsubscribe_token"


async def test_watch_asset_and_project(client: AsyncClient, session: AsyncSession):
    owner = await mk_user(session)
    stranger = await mk_user(session)
    asset = await mk_asset(session, owner, title="Watched")
    await session.commit()
    await login_as(client, owner)
    r = await client.get(f"/api/assets/{asset.id}/watch")
    assert r.json() == {"level": None, "via_project": None, "own": True}
    r = await client.put(f"/api/assets/{asset.id}/watch", json={"level": "watch"})
    assert r.json()["level"] == "watch"
    listed = (await client.get("/api/watches")).json()
    assert listed["total"] == 1 and listed["items"][0]["asset"]["title"] == "Watched"
    r = await client.delete(f"/api/assets/{asset.id}/watch")
    assert r.json()["level"] is None

    r = await client.post("/api/projects", json={"name": "Watched project"})
    slug = r.json()["slug"]
    r = await client.put(f"/api/projects/{slug}/watch", json={"level": "all"})
    assert r.json() == {"level": "all"}
    assert (await client.get(f"/api/projects/{slug}/watch")).json() == {"level": "all"}

    await client.post("/api/auth/logout")
    await login_as(client, stranger)
    assert (
        await client.put(f"/api/assets/{asset.id}/watch", json={"level": "watch"})
    ).status_code == 404
    assert (await client.get(f"/api/projects/{slug}/watch")).status_code == 404


async def test_stream_needs_a_browser_session(client: AsyncClient, session: AsyncSession):
    assert (await client.get("/api/notifications/stream")).status_code == 401
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)
    expires = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    token = (
        await client.post("/api/auth/tokens", json={"name": "ps", "expires_at": expires})
    ).json()
    client.cookies.clear()
    r = await client.get(
        "/api/notifications/stream", headers={"Authorization": f"Bearer {token['token']}"}
    )
    assert r.status_code == 403 and r.json()["code"] == "stream_browser_only"
