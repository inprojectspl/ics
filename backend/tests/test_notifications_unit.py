"""Pure unit tests for the notifications package: registry, URL validation,
Google Chat payload structure. No DB, no FastAPI.

DB-backed scenarios (link resolver, dispatcher) are in separate files
`test_notifications_resolver.py` and `test_notifications_dispatcher.py`.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services import notifications
from app.services.notifications._providers.google_chat import GoogleChatProvider
from app.services.notifications._types import (
    AssetLink,
    AssetLinkVisibility,
    InvalidWebhookUrlError,
    NotificationContext,
    NotificationProviderId,
    UnknownProviderError,
)

# ============================================================
#  Registry / public API
# ============================================================


def test_list_provider_infos_returns_google_chat():
    infos = notifications.list_provider_infos()
    assert len(infos) >= 1
    by_id = {i.id: i for i in infos}
    gc = by_id[NotificationProviderId.GOOGLE_CHAT]
    assert gc.display_name == "Google Chat"
    assert "chat.googleapis.com" in gc.url_hint


def test_get_provider_by_id_returns_instance():
    p = notifications.get_provider(NotificationProviderId.GOOGLE_CHAT)
    assert p.id is NotificationProviderId.GOOGLE_CHAT


def test_get_provider_by_string_returns_instance():
    p = notifications.get_provider("google_chat")
    assert p.id is NotificationProviderId.GOOGLE_CHAT


def test_get_provider_unknown_id_raises():
    with pytest.raises(UnknownProviderError):
        notifications.get_provider("slack")


def test_validate_provider_url_happy_path():
    notifications.validate_provider_url(
        "google_chat",
        "https://chat.googleapis.com/v1/spaces/AAA/messages?key=x&token=y",
    )


def test_validate_provider_url_wrong_provider_raises():
    with pytest.raises(UnknownProviderError):
        notifications.validate_provider_url("nope", "https://x")


def test_validate_provider_url_wrong_url_raises():
    with pytest.raises(InvalidWebhookUrlError):
        notifications.validate_provider_url("google_chat", "https://example.com/x")


# ============================================================
#  GoogleChatProvider.accepts_url
# ============================================================


_GC = GoogleChatProvider()


@pytest.mark.parametrize(
    "url",
    [
        "https://chat.googleapis.com/v1/spaces/AAA/messages?key=x&token=y",
        "https://chat.googleapis.com/v1/spaces/B/messages",
        "https://CHAT.GOOGLEAPIS.COM/x",  # case-insensitive host
    ],
)
def test_accepts_canonical_chat_url(url: str):
    assert _GC.accepts_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "",
        "http://chat.googleapis.com/x",  # http, not https
        "https://chat.googleapis.com.attacker.example/x",  # subdomain attack
        "https://attacker.example/chat.googleapis.com",  # path
        "https://hooks.slack.com/services/T00/B00/abc",  # another provider
        "https://chat.googleapis.com:8080/x",  # non-standard port (host-only allowlist)
        "https://user:pass@chat.googleapis.com/x",  # userinfo
        "javascript:alert(1)",
        "file:///etc/passwd",
        "http://127.0.0.1/x",
        "http://169.254.169.254/x",  # IMDS
        "not-a-url",
    ],
)
def test_rejects_non_google_chat_url(url: str):
    # Rejecting port 8080 is defensive: Google Chat publishes webhooks on 443.
    # Allowing a non-standard port opens a door to DNS rebinding, where an
    # attacker points the host at chat.googleapis.com via DNS poisoning
    # and listens on :8080 on another IP.
    assert _GC.accepts_url(url) is False


# ============================================================
#  GoogleChatProvider.send: payload contract
# ============================================================


def _ctx(**overrides: Any) -> NotificationContext:
    defaults = {
        "asset_title": "API Documentation",
        "asset_slug": "docs-api",
        "version": 7,
        "commit_sha": "abcdef1234567890" * 2 + "abcd",
        "file_count": 12,
        "security_status": "clean",
        "link": AssetLink(
            url="https://ics.example.com/s/token123",
            visibility=AssetLinkVisibility.ORG,
        ),
    }
    return NotificationContext(**(defaults | overrides))


class _CapturingClient:
    """Minimal `httpx.AsyncClient` stub: records calls, returns 200."""

    def __init__(self, *_: Any, **kw: Any) -> None:
        self.timeout = kw.get("timeout")
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __aenter__(self) -> _CapturingClient:
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        return None

    async def post(self, url: str, json: dict[str, Any]) -> Any:
        self.calls.append((url, json))

        class _Resp:
            status_code = 200
            text = ""

        return _Resp()


@pytest.mark.asyncio
async def test_send_posts_card_with_link_button(monkeypatch):
    captured: list[_CapturingClient] = []

    def _factory(*a: Any, **kw: Any) -> _CapturingClient:
        c = _CapturingClient(*a, **kw)
        captured.append(c)
        return c

    monkeypatch.setattr(
        "app.services.notifications._providers.google_chat.httpx.AsyncClient",
        _factory,
    )
    url = "https://chat.googleapis.com/v1/spaces/A/messages?key=x&token=y"
    await _GC.send(url, _ctx())

    assert len(captured) == 1
    sent_url, body = captured[0].calls[0]
    assert sent_url == url
    cards = body["cardsV2"]
    assert len(cards) == 1
    card = cards[0]["card"]
    # Header with the asset title and visibility in the subtitle.
    assert card["header"]["title"] == "API Documentation"
    assert card["header"]["subtitle"] == "ICS · synced (organization only)"
    # The section has widgets with a button linking to ICS.
    widgets = card["sections"][0]["widgets"]
    button_list = next(w for w in widgets if "buttonList" in w)
    btn = button_list["buttonList"]["buttons"][0]
    assert btn["onClick"]["openLink"]["url"] == "https://ics.example.com/s/token123"
    # Commit shortened to 8 characters.
    commit_widget = next(
        w for w in widgets if w.get("decoratedText", {}).get("topLabel") == "Commit"
    )
    assert len(commit_widget["decoratedText"]["text"]) == 8


@pytest.mark.asyncio
async def test_send_includes_security_warning_when_not_clean(monkeypatch):
    captured: list[_CapturingClient] = []
    monkeypatch.setattr(
        "app.services.notifications._providers.google_chat.httpx.AsyncClient",
        lambda *a, **kw: (lambda c: (captured.append(c), c)[1])(_CapturingClient()),
    )
    await _GC.send(
        "https://chat.googleapis.com/x",
        _ctx(security_status="warn"),
    )
    widgets = captured[0].calls[0][1]["cardsV2"][0]["card"]["sections"][0]["widgets"]
    sec = next(w for w in widgets if w.get("decoratedText", {}).get("topLabel") == "Security scan")
    assert "warn" in sec["decoratedText"]["text"]


@pytest.mark.asyncio
async def test_send_omits_security_widget_when_clean(monkeypatch):
    captured: list[_CapturingClient] = []
    monkeypatch.setattr(
        "app.services.notifications._providers.google_chat.httpx.AsyncClient",
        lambda *a, **kw: (lambda c: (captured.append(c), c)[1])(_CapturingClient()),
    )
    await _GC.send("https://chat.googleapis.com/x", _ctx(security_status="clean"))
    widgets = captured[0].calls[0][1]["cardsV2"][0]["card"]["sections"][0]["widgets"]
    assert not any(w.get("decoratedText", {}).get("topLabel") == "Security scan" for w in widgets)


@pytest.mark.asyncio
async def test_send_uses_public_label_for_public_link(monkeypatch):
    captured: list[_CapturingClient] = []
    monkeypatch.setattr(
        "app.services.notifications._providers.google_chat.httpx.AsyncClient",
        lambda *a, **kw: (lambda c: (captured.append(c), c)[1])(_CapturingClient()),
    )
    ctx = _ctx(
        link=AssetLink(url="https://x/s/t", visibility=AssetLinkVisibility.PUBLIC),
    )
    await _GC.send("https://chat.googleapis.com/x", ctx)
    subtitle = captured[0].calls[0][1]["cardsV2"][0]["card"]["header"]["subtitle"]
    assert "public link" in subtitle


@pytest.mark.asyncio
async def test_send_renders_the_card_in_polish(monkeypatch):
    captured: list[_CapturingClient] = []
    monkeypatch.setattr(
        "app.services.notifications._providers.google_chat.httpx.AsyncClient",
        lambda *a, **kw: (lambda c: (captured.append(c), c)[1])(_CapturingClient()),
    )
    await _GC.send(
        "https://chat.googleapis.com/x",
        _ctx(locale="pl", file_count=3, security_status="critical"),
    )
    card = captured[0].calls[0][1]["cardsV2"][0]["card"]
    assert card["header"]["subtitle"] == "ICS · zsynchronizowano (tylko organizacja)"
    labels = {
        w["decoratedText"]["topLabel"]: w["decoratedText"]["text"]
        for w in card["sections"][0]["widgets"]
        if "decoratedText" in w
    }
    assert labels["Wersja"].endswith("3 pliki")
    assert labels["Skan bezpieczeństwa"] == "⚠ krytyczny"
    button = next(w for w in card["sections"][0]["widgets"] if "buttonList" in w)
    assert button["buttonList"]["buttons"][0]["text"] == "Otwórz w ICS"


@pytest.mark.asyncio
async def test_send_silent_on_non_googlechat_url(monkeypatch):
    """Defense in depth: someone replaced the DB row by hand. The gate in send()
    must abort the request before httpx touches the network."""
    called = False

    class _ShouldNotCall:
        def __init__(self, *_a: Any, **_kw: Any) -> None:
            nonlocal called
            called = True

        async def __aenter__(self) -> _ShouldNotCall:
            return self

        async def __aexit__(self, *_exc: Any) -> None:
            return None

    monkeypatch.setattr(
        "app.services.notifications._providers.google_chat.httpx.AsyncClient",
        _ShouldNotCall,
    )
    await _GC.send("https://example.com/x", _ctx())
    assert called is False


@pytest.mark.asyncio
async def test_send_swallows_network_errors(monkeypatch):
    class _Boom:
        def __init__(self, *_a: Any, **_kw: Any) -> None: ...

        async def __aenter__(self) -> _Boom:
            return self

        async def __aexit__(self, *_exc: Any) -> None:
            return None

        async def post(self, *_a: Any, **_kw: Any) -> Any:
            raise RuntimeError("network down")

    monkeypatch.setattr(
        "app.services.notifications._providers.google_chat.httpx.AsyncClient",
        _Boom,
    )
    # Must not raise.
    await _GC.send("https://chat.googleapis.com/x", _ctx())


def test_provider_subclass_must_declare_classvars():
    """`__init_subclass__` in the base class enforces id/display_name/url_hint."""
    from app.services.notifications._providers._base import NotificationProvider

    with pytest.raises(TypeError, match="ClassVar"):

        class Bad(NotificationProvider):  # pragma: no cover - init-time raise
            async def send(self, url: str, ctx: Any) -> None: ...

            def accepts_url(self, url: str) -> bool:
                return False
