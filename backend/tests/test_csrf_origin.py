"""Cross-site state-changing requests made with the session cookie are refused."""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.oauth import tokens as tokens_mod
from tests.conftest import login_as, mk_asset, mk_user

_AUDIENCE = "https://ics-test.example/mcp"


async def _logged_in_asset(client, session):
    user = await mk_user(session)
    asset = await mk_asset(session, user)
    await session.commit()
    await login_as(client, user)
    return user, asset


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example"},
        {"Origin": "null"},
        {"Sec-Fetch-Site": "cross-site"},
        # The HTML bundle viewer is a sibling subdomain serving uploaded pages.
        {"Sec-Fetch-Site": "same-site"},
    ],
)
async def test_cookie_post_from_foreign_origin_is_rejected(client, session, headers):
    _user, asset = await _logged_in_asset(client, session)

    r = await client.post(f"/api/assets/{asset.id}/pin", headers=headers)

    assert r.status_code == 403
    assert r.json()["code"] == "csrf_origin_rejected"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": get_settings().base_url},
        {"Origin": get_settings().cors_origins_list[0]},
        {"Sec-Fetch-Site": "same-origin"},
        {},
    ],
)
async def test_cookie_post_from_own_origin_passes(client, session, headers):
    _user, asset = await _logged_in_asset(client, session)

    r = await client.post(f"/api/assets/{asset.id}/pin", headers=headers)

    assert r.status_code == 200


@pytest.mark.asyncio
async def test_safe_methods_are_not_checked(client, session):
    _user, asset = await _logged_in_asset(client, session)

    r = await client.get(f"/api/assets/{asset.id}", headers={"Origin": "https://evil.example"})

    assert r.status_code == 200


@pytest.mark.asyncio
async def test_bearer_request_with_foreign_origin_passes(client, session, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "mcp_resource_uri", _AUDIENCE)
    monkeypatch.setattr(s, "debug", True)
    user = await mk_user(session)
    asset = await mk_asset(session, user)
    await session.commit()
    token, _jti = tokens_mod.sign_access_jwt(
        settings=s,
        user=user,
        client_id_external="ics-mcp-stdio",
        scopes=["ics"],
        audience=_AUDIENCE,
    )
    client.cookies.set("unrelated", "1")

    r = await client.post(
        f"/api/assets/{asset.id}/pin",
        headers={"Authorization": f"Bearer {token}", "Origin": "https://evil.example"},
    )

    assert r.status_code == 200


# ---------- HTML bundle viewer origin ----------
# The viewer serves uploaded pages on a sibling host; listing it in
# ICS_CORS_ORIGINS must not let a bundle's script use the viewer's session.


def _viewer_in_cors(monkeypatch) -> str:
    s = get_settings()
    viewer = s.html_viewer_origin
    monkeypatch.setattr(s, "cors_origins", f"{s.base_url},{viewer}")
    return viewer


def test_viewer_origin_is_dropped_from_cors(monkeypatch):
    viewer = _viewer_in_cors(monkeypatch)

    assert viewer not in get_settings().cors_origins_list
    assert get_settings().base_url in get_settings().cors_origins_list


@pytest.mark.asyncio
async def test_cookie_post_from_viewer_origin_is_rejected_even_if_in_cors(
    client, session, monkeypatch
):
    viewer = _viewer_in_cors(monkeypatch)
    _user, asset = await _logged_in_asset(client, session)

    r = await client.post(f"/api/assets/{asset.id}/pin", headers={"Origin": viewer})

    assert r.status_code == 403
