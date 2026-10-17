"""Tests for `oauth/server/authorize.py`: the consent POST."""

from __future__ import annotations

import pytest

from tests.conftest import login_as as _login
from tests.conftest import mk_user


@pytest.mark.asyncio
async def test_post_authorize_allow_returns_code_in_redirect_url(client, session):
    """POST consent with allow + state -> 302 to redirect_uri with `code` and `state`."""
    from urllib.parse import parse_qs, urlparse

    from tests.conftest import (
        STATE_TOKEN_RE,
        make_pkce,
        register_oauth_client,
        resource_uri,
    )

    dcr = await register_oauth_client(client, name="Allow Test")
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    _, code_challenge = make_pkce()
    auth_r = await client.get(
        "/api/auth/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": dcr["client_id"],
            "redirect_uri": "http://localhost:9000/callback",
            "scope": "ics",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "resource": resource_uri(),
            "state": "csrf-XYZ",
        },
    )
    assert auth_r.status_code == 200
    state_token = STATE_TOKEN_RE.search(auth_r.text).group(1)

    post_r = await client.post(
        "/api/auth/oauth/authorize",
        data={"state_token": state_token, "decision": "allow"},
        follow_redirects=False,
    )
    assert post_r.status_code == 302
    qs = parse_qs(urlparse(post_r.headers["location"]).query)
    assert "code" in qs
    assert qs["state"] == ["csrf-XYZ"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stored,header,lang,allow",
    [
        (None, None, "en", "Allow"),
        (None, "pl-PL,pl;q=0.9", "pl", "Pozwól"),
        ("en", "pl", "en", "Allow"),
        ("pl", "en", "pl", "Pozwól"),
    ],
)
async def test_consent_page_follows_user_then_browser_locale(
    client, session, stored, header, lang, allow
):
    from tests.conftest import make_pkce, register_oauth_client, resource_uri

    dcr = await register_oauth_client(client, name="Locale Test")
    user = await mk_user(session, locale=stored)
    await session.commit()
    await _login(client, user)
    _, code_challenge = make_pkce()
    r = await client.get(
        "/api/auth/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": dcr["client_id"],
            "redirect_uri": "http://localhost:9000/callback",
            "scope": "ics",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "resource": resource_uri(),
        },
        headers={"Accept-Language": header} if header else {},
    )
    assert r.status_code == 200
    assert f'<html lang="{lang}">' in r.text
    assert f'class="ok">{allow}</button>' in r.text
