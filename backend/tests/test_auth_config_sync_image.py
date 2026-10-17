"""`/api/auth/config` exposes the ics-sync image the binding snippet uses."""

from __future__ import annotations

import pytest

from app.config import get_settings


@pytest.mark.asyncio
async def test_config_returns_configured_sync_image(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "sync_image", "registry.test/ics-sync:3")
    r = await client.get("/api/auth/config")
    assert r.status_code == 200
    assert r.json()["sync_image"] == "registry.test/ics-sync:3"


@pytest.mark.asyncio
async def test_config_sync_image_is_empty_by_default(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "sync_image", "")
    r = await client.get("/api/auth/config")
    assert r.json()["sync_image"] == ""
