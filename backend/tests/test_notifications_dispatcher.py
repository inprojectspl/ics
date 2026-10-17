"""Binding sync notification dispatcher: orchestrates provider + link.

Checks the silent-skip conditions:
- no webhook_url and no provider,
- unknown provider in the DB (e.g. after it was removed from the code),
- no active share link,
- happy path: provider.send is called with the correct context.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.config import get_settings
from app.models import GitLabBinding, ShareLink
from app.services.notifications import dispatch_sync_notification
from app.slug import generate_token
from tests.conftest import mk_asset, mk_user


def _binding(asset_id, *, provider: str | None, webhook_url: str | None) -> GitLabBinding:
    return GitLabBinding(
        asset_id=asset_id,
        provider=provider,
        webhook_url=webhook_url,
        public_key="-----BEGIN PUBLIC KEY-----\nfake\n-----END PUBLIC KEY-----",
    )


async def _setup(session, *, with_share: bool = True):
    user = await mk_user(session)
    asset = await mk_asset(session, user)
    if with_share:
        session.add(ShareLink(asset_id=asset.id, token=generate_token(), mode="org_sso"))
    await session.flush()
    return asset


class _RecordingProvider:
    """Capture-mode replacement registered via monkeypatch."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def accepts_url(self, _url: str) -> bool:
        return True

    async def send(self, url: str, ctx: Any) -> None:
        self.calls.append((url, ctx))


def _install_recording_provider(monkeypatch) -> _RecordingProvider:
    rec = _RecordingProvider()
    monkeypatch.setattr(
        "app.services.notifications._dispatcher.get_provider",
        lambda _id: rec,
    )
    return rec


@pytest.mark.asyncio
async def test_skip_when_no_webhook_and_no_provider(session, monkeypatch):
    rec = _install_recording_provider(monkeypatch)
    asset = await _setup(session)
    binding = _binding(asset.id, provider=None, webhook_url=None)
    session.add(binding)
    await session.flush()

    await dispatch_sync_notification(
        binding=binding,
        asset=asset,
        new_version=2,
        file_count=3,
        commit_sha="abc1234",
        security_status="clean",
        session=session,
        settings=get_settings(),
    )
    assert rec.calls == []


@pytest.mark.asyncio
async def test_skip_when_provider_unknown(session, monkeypatch):
    """The DB row has a legacy provider ID that no longer exists in the code:
    the dispatcher logs and returns instead of crashing the sync route."""
    from app.services.notifications._types import UnknownProviderError

    def _boom(_id: str) -> Any:
        raise UnknownProviderError("removed provider")

    monkeypatch.setattr(
        "app.services.notifications._dispatcher.get_provider",
        _boom,
    )
    asset = await _setup(session)
    binding = _binding(asset.id, provider="dropped_legacy", webhook_url="https://x")
    session.add(binding)
    await session.flush()

    await dispatch_sync_notification(
        binding=binding,
        asset=asset,
        new_version=2,
        file_count=3,
        commit_sha="abc1234",
        security_status=None,
        session=session,
        settings=get_settings(),
    )
    # No raise = OK.


@pytest.mark.asyncio
async def test_skip_when_no_share_link(session, monkeypatch):
    rec = _install_recording_provider(monkeypatch)
    asset = await _setup(session, with_share=False)
    binding = _binding(
        asset.id,
        provider="google_chat",
        webhook_url="https://chat.googleapis.com/x",
    )
    session.add(binding)
    await session.flush()

    await dispatch_sync_notification(
        binding=binding,
        asset=asset,
        new_version=2,
        file_count=3,
        commit_sha="abc1234",
        security_status="clean",
        session=session,
        settings=get_settings(),
    )
    assert rec.calls == []


@pytest.mark.asyncio
async def test_happy_path_sends_context_to_provider(session, monkeypatch):
    rec = _install_recording_provider(monkeypatch)
    asset = await _setup(session)
    binding = _binding(
        asset.id,
        provider="google_chat",
        webhook_url="https://chat.googleapis.com/v1/spaces/A/messages",
    )
    session.add(binding)
    await session.flush()

    await dispatch_sync_notification(
        binding=binding,
        asset=asset,
        new_version=7,
        file_count=12,
        commit_sha="deadbeef00",
        security_status="warn",
        session=session,
        settings=get_settings(),
    )
    assert len(rec.calls) == 1
    url, ctx = rec.calls[0]
    assert url == binding.webhook_url
    assert ctx.version == 7
    assert ctx.file_count == 12
    assert ctx.commit_sha == "deadbeef00"
    assert ctx.security_status == "warn"
    assert ctx.asset_slug == asset.slug
    assert ctx.link is not None
    assert ctx.link.url.endswith("/s/" + ctx.link.url.rsplit("/", 1)[1])


@pytest.mark.parametrize(
    "author_locale,owner_locale,expected",
    [(None, None, "en"), ("pl", "en", "pl"), (None, "pl", "pl")],
)
async def test_card_locale_follows_binding_author_then_owner(
    session, monkeypatch, author_locale, owner_locale, expected
):
    rec = _install_recording_provider(monkeypatch)
    owner = await mk_user(session, locale=owner_locale)
    author = await mk_user(session, locale=author_locale)
    asset = await mk_asset(session, owner)
    session.add(ShareLink(asset_id=asset.id, token=generate_token(), mode="org_sso"))
    binding = _binding(
        asset.id, provider="google_chat", webhook_url="https://chat.googleapis.com/x"
    )
    binding.created_by = author.id
    session.add(binding)
    await session.flush()

    await dispatch_sync_notification(
        binding=binding,
        asset=asset,
        new_version=2,
        file_count=1,
        commit_sha="abc",
        security_status=None,
        session=session,
        settings=get_settings(),
    )
    assert rec.calls[0][1].locale == expected
