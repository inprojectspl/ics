"""Fan-out (ADR-0023, section 4): recipients, access, mutes, preferences,
debounced updates and the channel batches."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import permissions
from app.config import get_settings
from app.models import (
    AssetProjectShare,
    AssetShare,
    EmailOutbox,
    NotificationPreference,
    Project,
    ProjectMember,
    User,
    Watch,
)
from app.redis_client import get_redis
from app.services.notifications import batches, fanout, inbox, preferences, recipients, schedule
from app.slug import generate_slug
from tests.conftest import mk_admin, mk_asset, mk_user


async def _project(session: AsyncSession, owner: User, *members: User) -> Project:
    project = Project(slug=generate_slug(), name=f"P {generate_slug(6)}", created_by=owner.id)
    session.add(project)
    await session.flush()
    now = datetime.now(UTC)
    session.add(
        ProjectMember(project_id=project.id, user_id=owner.id, role="owner", accepted_at=now)
    )
    for m in members:
        session.add(
            ProjectMember(project_id=project.id, user_id=m.id, role="viewer", accepted_at=now)
        )
    await session.flush()
    return project


async def _inbox_codes(user: User) -> list[str]:
    entries, _ = await inbox.page(get_redis(), user.id, before=None, limit=50, unread_only=False)
    return [e.payload["c"] for e in entries]


async def test_update_reaches_watchers_with_access_only(session: AsyncSession):
    owner, member, outsider, muter = [await mk_user(session) for _ in range(4)]
    project = await _project(session, owner, member, muter)
    asset = await mk_asset(session, owner)
    asset.project_id = project.id
    session.add_all(
        [
            Watch(user_id=member.id, project_id=project.id, level="all"),
            Watch(user_id=outsider.id, asset_id=asset.id, level="watch"),
            Watch(user_id=muter.id, project_id=project.id, level="all"),
            Watch(user_id=muter.id, asset_id=asset.id, level="mute"),
        ]
    )
    await session.commit()

    count = await fanout.fan_out(
        session,
        get_redis(),
        get_settings(),
        code="asset.updated",
        asset_id=asset.id,
        actor_id=owner.id,
        excluded={owner.id},
        version=3,
        from_version=2,
    )
    assert count == 1
    assert await _inbox_codes(member) == ["asset.updated"]
    assert await _inbox_codes(outsider) == []
    assert await _inbox_codes(muter) == []
    assert await _inbox_codes(owner) == []
    [entry], _ = await inbox.page(get_redis(), member.id, before=None, limit=5, unread_only=False)
    assert entry.payload["n"] == 2 and entry.payload["fv"] == 2 and entry.payload["v"] == 3


async def test_owner_hears_about_others_edits_unless_opted_out(session: AsyncSession):
    owner = await mk_user(session)
    editor = await mk_user(session)
    asset = await mk_asset(session, owner)
    session.add(AssetShare(asset_id=asset.id, user_id=editor.id, role="editor"))
    await session.commit()
    kw = {
        "code": "asset.updated",
        "asset_id": asset.id,
        "actor_id": editor.id,
        "excluded": {editor.id},
        "version": 2,
    }
    assert await fanout.fan_out(session, get_redis(), get_settings(), **kw) == 1
    session.add(NotificationPreference(user_id=owner.id, watch_own_assets=False, events={}))
    await session.commit()
    assert await fanout.fan_out(session, get_redis(), get_settings(), **kw) == 0


async def test_master_switch_off_silences_everything(session: AsyncSession):
    owner = await mk_user(session)
    member = await mk_user(session)
    project = await _project(session, owner, member)
    asset = await mk_asset(session, owner)
    asset.project_id = project.id
    session.add(Watch(user_id=member.id, project_id=project.id, level="new"))
    session.add(NotificationPreference(user_id=member.id, enabled=False, events={}))
    await session.commit()
    n = await fanout.fan_out(
        session,
        get_redis(),
        get_settings(),
        code="asset.created",
        asset_id=asset.id,
        actor_id=owner.id,
        excluded={owner.id},
        project_id=project.id,
    )
    assert n == 0


async def test_new_level_ignores_updates_but_gets_new_assets(session: AsyncSession):
    owner = await mk_user(session)
    member = await mk_user(session)
    project = await _project(session, owner, member)
    asset = await mk_asset(session, owner)
    asset.project_id = project.id
    session.add(Watch(user_id=member.id, project_id=project.id, level="new"))
    await session.commit()
    redis, settings = get_redis(), get_settings()
    base = {"asset_id": asset.id, "actor_id": owner.id, "excluded": {owner.id}}
    assert (
        await fanout.fan_out(session, redis, settings, code="asset.updated", version=2, **base) == 0
    )
    assert (
        await fanout.fan_out(
            session, redis, settings, code="asset.created", project_id=project.id, **base
        )
        == 1
    )


async def test_project_share_watchers_hear_about_updates(session: AsyncSession):
    owner = await mk_user(session)
    other_owner = await mk_user(session)
    member = await mk_user(session)
    other = await _project(session, other_owner, member)
    asset = await mk_asset(session, owner)
    session.add(AssetProjectShare(asset_id=asset.id, project_id=other.id, role="viewer"))
    session.add(Watch(user_id=member.id, project_id=other.id, level="all"))
    await session.commit()
    n = await fanout.fan_out(
        session,
        get_redis(),
        get_settings(),
        code="asset.updated",
        asset_id=asset.id,
        actor_id=owner.id,
        excluded={owner.id},
        version=2,
    )
    assert n == 1


async def test_readers_filter_matches_effective_role(session: AsyncSession):
    owner = await mk_user(session)
    admin = await mk_admin(session)
    member = await mk_user(session)
    pending = await mk_user(session)
    direct = await mk_user(session)
    via_share = await mk_user(session)
    outsider = await mk_user(session)
    project = await _project(session, owner, member)
    session.add(ProjectMember(project_id=project.id, user_id=pending.id, role="viewer"))
    other = await _project(session, owner, via_share)
    asset = await mk_asset(session, owner)
    asset.project_id = project.id
    session.add(AssetShare(asset_id=asset.id, user_id=direct.id, role="viewer"))
    session.add(AssetProjectShare(asset_id=asset.id, project_id=other.id, role="viewer"))
    await session.flush()
    users = [owner, admin, member, pending, direct, via_share, outsider]
    readable = {r.id for r in await recipients.readable(session, asset, [u.id for u in users])}
    for u in users:
        expected = await permissions.effective_role(session, u, asset) is not None
        assert (u.id in readable) == expected, u.email
    assert outsider.id not in readable and pending.id not in readable


async def test_email_batch_skips_entries_read_in_the_app(session: AsyncSession, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_host", "mail.invalid")
    monkeypatch.setattr(settings, "notifications_email_batch_seconds", 0)
    monkeypatch.setattr("app.email_outbox.aiosmtplib.send", AsyncMock())
    owner = await mk_user(session)
    member = await mk_user(session, locale="pl")
    project = await _project(session, owner, member)
    session.add(NotificationPreference(user_id=member.id, email_mode="batched", events={}))
    session.add(Watch(user_id=member.id, project_id=project.id, level="new"))
    first = await mk_asset(session, owner, title="First")
    second = await mk_asset(session, owner, title="Second")
    first.project_id = second.project_id = project.id
    await session.commit()
    redis = get_redis()
    for a in (first, second):
        await fanout.fan_out(
            session,
            redis,
            settings,
            code="asset.created",
            asset_id=a.id,
            actor_id=owner.id,
            excluded={owner.id},
            project_id=project.id,
        )
    entries, _ = await inbox.page(redis, member.id, before=None, limit=5, unread_only=False)
    await inbox.mark_read(redis, member.id, [e.id for e in entries if e.payload["t"] == "Second"])
    assert await schedule.claim(redis, "mail") == [str(member.id)]
    assert await batches.send_mail(session, redis, settings, str(member.id)) == 1
    mail = (
        await session.scalars(select(EmailOutbox).where(EmailOutbox.to_email == member.email))
    ).one()
    assert mail.purpose == "notification"
    assert "First" in mail.body and "Second" not in mail.body


async def test_dead_chat_webhook_is_disabled_and_reported(session: AsyncSession, monkeypatch):
    settings = get_settings()
    owner = await mk_user(session)
    member = await mk_user(session)
    project = await _project(session, owner, member)
    row = NotificationPreference(user_id=member.id, events={})
    preferences.set_chat_webhook(
        row, "https://chat.googleapis.com/v1/spaces/AAA/messages?key=k&token=t", settings
    )
    session.add(row)
    session.add(Watch(user_id=member.id, project_id=project.id, level="new"))
    asset = await mk_asset(session, owner)
    asset.project_id = project.id
    await session.commit()
    monkeypatch.setattr(settings, "notifications_chat_batch_seconds", 0)
    post = AsyncMock(return_value=404)
    monkeypatch.setattr(
        "app.services.notifications._providers.google_chat.GoogleChatProvider.post", post
    )
    redis = get_redis()
    await fanout.fan_out(
        session,
        redis,
        settings,
        code="asset.created",
        asset_id=asset.id,
        actor_id=owner.id,
        excluded={owner.id},
        project_id=project.id,
    )
    assert await schedule.claim(redis, "chat") == [str(member.id)]
    await batches.send_chat(session, redis, settings, str(member.id))
    post.assert_awaited_once()
    await session.refresh(row)
    assert row.chat_enabled is False and row.chat_error_code == "rejected"
    assert (await _inbox_codes(member))[0] == "channel.chat_disabled"


async def test_sweeper_merges_a_burst_of_versions(session: AsyncSession, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "notifications_update_debounce_seconds", 0)
    owner = await mk_user(session)
    watcher = await mk_user(session)
    asset = await mk_asset(session, owner)
    session.add(AssetShare(asset_id=asset.id, user_id=watcher.id, role="viewer"))
    session.add(Watch(user_id=watcher.id, asset_id=asset.id, level="watch"))
    asset.version = 4
    await session.commit()
    redis = get_redis()
    for v in (2, 3, 4):
        await schedule.note_update(redis, asset.id, v, owner.id, settings)

    @asynccontextmanager
    async def _session():
        yield session

    monkeypatch.setattr("app.jobs.tasks.notify.SessionLocal", _session)
    from app.jobs.tasks.notify import notifications_sweeper

    done = await notifications_sweeper({})
    assert done["updated"] == 1
    [entry], _ = await inbox.page(redis, watcher.id, before=None, limit=5, unread_only=False)
    assert (entry.payload["fv"], entry.payload["v"], entry.payload["n"]) == (2, 4, 3)
    assert await _inbox_codes(owner) == []


async def test_sweeper_names_every_writer_of_a_burst(session: AsyncSession, monkeypatch):
    """Two people edit within one window: nobody is told the other one made
    their edit, and an onlooker sees both names."""
    from app.services.notifications.render import render

    settings = get_settings()
    monkeypatch.setattr(settings, "notifications_update_debounce_seconds", 0)
    owner = await mk_user(session)
    anna = await mk_user(session, display_name="Anna")
    bob = await mk_user(session, display_name="Bob")
    watcher = await mk_user(session)
    asset = await mk_asset(session, owner)
    for u in (anna, bob, watcher):
        session.add(AssetShare(asset_id=asset.id, user_id=u.id, role="editor"))
        session.add(Watch(user_id=u.id, asset_id=asset.id, level="watch"))
    asset.version = 3
    await session.commit()
    redis = get_redis()
    await schedule.note_update(redis, asset.id, 2, anna.id, settings)
    await schedule.note_update(redis, asset.id, 3, bob.id, settings)

    @asynccontextmanager
    async def _session():
        yield session

    monkeypatch.setattr("app.jobs.tasks.notify.SessionLocal", _session)
    from app.jobs.tasks.notify import notifications_sweeper

    assert (await notifications_sweeper({}))["updated"] == 1

    async def entry_of(user: User):
        [entry], _ = await inbox.page(redis, user.id, before=None, limit=5, unread_only=False)
        return entry

    seen = await entry_of(watcher)
    assert (seen.payload["ai"], seen.payload["an"], seen.payload["na"]) == (
        str(bob.id),
        "Bob, Anna",
        2,
    )
    assert render(seen.id, seen.payload, "en", settings).body == (
        "Changes by Bob, Anna, up to version 3"
    )
    for user, other in ((anna, bob), (bob, anna)):
        p = (await entry_of(user)).payload
        assert (p["ai"], p["an"], p.get("na")) == (str(other.id), other.display_name, None)


async def test_push_delivery_prunes_dead_devices(session: AsyncSession, monkeypatch):
    import httpx
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    from app.models import PushSubscription
    from app.services.notifications.channels import vapid

    settings = get_settings()
    private, _ = vapid.generate()
    monkeypatch.setattr(settings, "vapid_private_key", private)
    monkeypatch.setattr(settings, "vapid_subject", "mailto:ops@example.com")
    owner = await mk_user(session)
    member = await mk_user(session)
    project = await _project(session, owner, member)
    session.add(Watch(user_id=member.id, project_id=project.id, level="new"))
    asset = await mk_asset(session, owner)
    asset.project_id = project.id
    browser = ec.generate_private_key(ec.SECP256R1()).public_key()
    p256dh = vapid.b64url(
        browser.public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
    )
    for name in ("ok", "gone", "broken"):
        session.add(
            PushSubscription(
                user_id=member.id,
                endpoint=f"https://fcm.googleapis.com/fcm/send/{name}",
                p256dh=p256dh,
                auth=vapid.b64url(b"0123456789abcdef"),
            )
        )
    await session.commit()
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        status = {"ok": 201, "gone": 410}.get(request.url.path.rsplit("/", 1)[-1], 500)
        return httpx.Response(status)

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr("app.services.notifications.channels.webpush.client", lambda: mock_client)
    await fanout.fan_out(
        session,
        get_redis(),
        settings,
        code="asset.created",
        asset_id=asset.id,
        actor_id=owner.id,
        excluded={owner.id},
        project_id=project.id,
    )
    assert len(seen) == 3
    sent = seen[0]
    assert sent.headers["content-encoding"] == "aes128gcm"
    assert sent.headers["authorization"].startswith("vapid t=")
    assert len(sent.headers["topic"]) <= 32
    rows = {
        s.endpoint.rsplit("/", 1)[-1]: s
        for s in (
            await session.scalars(
                select(PushSubscription).where(PushSubscription.user_id == member.id)
            )
        )
    }
    assert set(rows) == {"ok", "broken"}
    assert rows["ok"].last_success_at is not None
    assert rows["broken"].failures == 1
