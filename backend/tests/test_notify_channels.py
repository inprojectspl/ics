"""Delivery channels (ADR-0023, section 7) and the live stream."""

from __future__ import annotations

import asyncio
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import http_ece
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from joserfc import jwt
from joserfc.jwk import ECKey

from app.config import get_settings
from app.email_templates_notify import notification_digest
from app.redis_client import get_redis
from app.routes.notifications.stream import _Viewer, notification_stream
from app.services.notifications import inbox, schedule
from app.services.notifications.channels import chat, vapid, webpush
from app.services.notifications.inbox import Delivery
from app.services.notifications.items import link_of
from app.services.notifications.render import render


def test_vapid_header_is_a_valid_es256_jwt_for_the_push_origin():
    private, public = vapid.generate()
    header = vapid.authorization(
        "https://fcm.googleapis.com/fcm/send/xyz", private, "mailto:ops@example.com"
    )
    token = header.split("t=", 1)[1].split(",", 1)[0]
    assert header.endswith(f"k={public}")
    point = vapid.b64url_decode(public)
    key = ECKey.import_key(
        {"kty": "EC", "crv": "P-256", "x": vapid.b64url(point[1:33]), "y": vapid.b64url(point[33:])}
    )
    claims = jwt.decode(token, key).claims
    assert claims["aud"] == "https://fcm.googleapis.com"
    assert claims["sub"] == "mailto:ops@example.com"


def test_push_payload_decrypts_with_the_browser_keys():
    browser = ec.generate_private_key(ec.SECP256R1())
    auth = b"0123456789abcdef"
    public = browser.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    target = webpush.PushTarget(
        endpoint="https://fcm.googleapis.com/x",
        p256dh=vapid.b64url(public),
        auth=vapid.b64url(auth),
    )
    body = webpush.encrypt(b'{"title":"Hi"}', target)
    plain = http_ece.decrypt(body, private_key=browser, auth_secret=auth, version="aes128gcm")
    assert plain == b'{"title":"Hi"}'


@pytest.mark.parametrize(
    ("endpoint", "allowed"),
    [
        ("https://fcm.googleapis.com/fcm/send/a", True),
        ("https://updates.push.services.mozilla.com/wpush/v2/a", True),
        ("https://web.push.apple.com/QK", True),
        ("https://wns2-par02p.notify.windows.com/w/?token=a", True),
        ("http://fcm.googleapis.com/fcm/send/a", False),
        ("https://fcm.googleapis.com:8443/a", False),
        ("https://user@fcm.googleapis.com/a", False),
        ("https://127.0.0.1/a", False),
        ("https://fcm.googleapis.com.evil.example/a", False),
    ],
)
def test_push_endpoint_allowlist(endpoint, allowed):
    assert webpush.endpoint_allowed(endpoint) is allowed


def test_push_topic_fits_the_header_limit():
    topic = webpush.topic_of("asset.updated:" + "x" * 200)
    assert len(topic) <= 32 and topic.replace("-", "").replace("_", "").isalnum()


@pytest.mark.parametrize(
    ("status", "result"),
    [
        (200, "ok"),
        (404, "disable"),
        (403, "disable"),
        (429, "retry"),
        (503, "retry"),
        (None, "retry"),
    ],
)
def test_chat_status_classification(status, result):
    assert chat.classify(status) == result


def _updated(n: int = 1) -> dict:
    p = {
        "c": "asset.updated",
        "as": "a1",
        "sl": "abc",
        "t": "API <spec>",
        "k": "md_single",
        "v": 5,
        "n": n,
        "an": "Anna",
        "ps": "crm",
        "pn": "CRM",
    }
    if n > 1:
        p["fv"] = 5 - n + 1
    return p


def test_links_open_viewer_or_diff():
    assert link_of(_updated()) == "/v/abc"
    assert link_of(_updated(3)) == "/v/abc/diff?from=2&to=5"
    assert link_of({"c": "asset.deleted", "ps": "crm"}) == "/projects/crm"
    assert link_of({"c": "channel.chat_disabled"}) == "/account/notifications"


def test_render_is_localised_and_pluralised():
    settings = get_settings()
    pl = render("1-0", _updated(5), "pl", settings)
    assert pl.title == "API <spec>: 5 nowych wersji"
    assert pl.body == "Anna zapisuje wersję 5"
    # The burst starts at v1: there is no earlier version to compare with.
    assert pl.url == settings.base_url.rstrip("/") + "/v/abc"
    en = render("1-0", _updated(2), "en", settings)
    assert en.title == "API <spec>: 2 new versions"


def test_chat_card_escapes_titles_and_links_each_row():
    settings = get_settings()
    card = chat.build_card([render("1-0", _updated(), "en", settings)], "en")
    widget = card["cardsV2"][0]["card"]["sections"][0]["widgets"][0]["decoratedText"]  # type: ignore[index]
    assert "&lt;spec&gt;" in widget["text"]
    assert widget["button"]["onClick"]["openLink"]["url"].endswith("/v/abc")


def test_digest_email_has_both_parts_and_escapes_html():
    settings = get_settings()
    items = [render("1-0", _updated(), "en", settings)]
    subject, text, html = notification_digest(
        items=items,
        inbox_url="https://ics/notifications",
        settings_url="https://ics/account/notifications",
        unsubscribe_url="https://ics/notifications/unsubscribe?token=t",
        daily=False,
        locale="en",
    )
    assert subject == "ICS: API <spec>: new version"
    assert "API <spec>" in text and "unsubscribe?token=t" in text
    assert "API &lt;spec&gt;" in html and "<spec>" not in html


def test_next_digest_is_today_or_tomorrow(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "notifications_digest_hour", 8)
    tz = ZoneInfo(settings.notifications_timezone)
    before = datetime(2026, 9, 28, 7, 30, tzinfo=tz)
    after = datetime(2026, 9, 28, 9, 0, tzinfo=tz)
    assert datetime.fromtimestamp(schedule.next_digest_at(settings, before), tz).day == 28
    assert datetime.fromtimestamp(schedule.next_digest_at(settings, after), tz).day == 29


async def test_debounce_claims_once_and_keeps_later_events():
    redis, settings = get_redis(), get_settings()
    asset_id = uuid4()
    settings_now = settings.model_copy(update={"notifications_update_debounce_seconds": 0})
    await schedule.note_update(redis, asset_id, 2, None, settings_now)
    await schedule.note_update(redis, asset_id, 3, None, settings_now)
    assert await schedule.claim(redis, "upd") == [str(asset_id)]
    assert await schedule.claim(redis, "upd") == []
    first, actors, last = await schedule.take_update(redis, str(asset_id))
    assert (first, actors, last) == (2, {"-"}, "-")
    await schedule.note_update(redis, asset_id, 4, None, settings_now)
    assert await schedule.claim(redis, "upd") == [str(asset_id)]


async def test_stream_sends_sync_then_live_events_and_replays_gaps():
    redis, settings = get_redis(), get_settings()
    uid = uuid4()
    [(old_id, _)] = await inbox.push_many(redis, [Delivery(uid, {"c": "asset.created"})], settings)
    [(missed_id, _)] = await inbox.push_many(
        redis, [Delivery(uid, {"c": "asset.created"})], settings
    )
    stream = notification_stream(viewer=_Viewer(uid=uid, sid=None), last_event_id=old_id)
    replay = await anext(stream)
    assert replay.event == "notification" and replay.id == missed_id
    sync = await anext(stream)
    assert sync.event == "sync" and sync.data == {"unread": 2}

    async def publish_later():
        await asyncio.sleep(0.05)
        await inbox.publish(redis, uid, "sync", {"unread": 0, "all_read": True})

    task = asyncio.create_task(publish_later())
    live = await asyncio.wait_for(anext(stream), timeout=3)
    await task
    assert live.event == "sync" and live.data["all_read"] is True
    await stream.aclose()


def test_every_asset_create_path_emits_the_created_event():
    """A new create path that forgets `emit_created` would silently skip
    project watchers (ADR-0023, section 4): each `Asset(` construction needs
    its own emit in the same file."""
    import re
    from pathlib import Path

    app_dir = Path(__file__).resolve().parents[1] / "app"
    counts = {
        p: (len(re.findall(r"=\s*Asset\(", text)), text.count("emit_created("))
        for p in app_dir.rglob("*.py")
        if (text := p.read_text())
    }
    creators = {p: c for p, c in counts.items() if c[0]}
    assert creators, "no create path found; the pattern is out of date"
    missing = {str(p): c for p, c in creators.items() if c[1] < c[0]}
    assert not missing


def test_list_unsubscribe_header_stays_a_plain_url():
    from app.email_outbox import _build_message

    url = "https://ics.example.com/api/notifications/unsubscribe?token=" + "x" * 120
    msg = _build_message(
        to_email="a@example.com",
        subject="s",
        body="b",
        body_html=None,
        smtp_from="ICS <no-reply@example.com>",
        list_unsubscribe_url=url,
    )
    raw = msg.as_bytes().decode()
    assert f"List-Unsubscribe: <{url}>\r\n" in raw
    assert "List-Unsubscribe-Post: List-Unsubscribe=One-Click\r\n" in raw
    assert "=?utf-8?" not in raw
