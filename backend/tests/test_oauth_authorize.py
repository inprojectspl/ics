"""Tests for `oauth/server/authorize.py`: the consent POST."""

from __future__ import annotations

import pytest

from tests.conftest import login_as as _login
from tests.conftest import mk_user


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["allow", "deny"])
@pytest.mark.parametrize("upstream_state", ["csrf-XYZ", "a+b&x=y#fragment%20?=ąć", ""])
async def test_post_authorize_preserves_state_in_decision_redirect(
    client, session, decision, upstream_state
):
    """Both consent decisions must return the exact state as one query parameter."""
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
            "state": upstream_state,
        },
    )
    assert auth_r.status_code == 200
    state_token = STATE_TOKEN_RE.search(auth_r.text).group(1)

    post_r = await client.post(
        "/api/auth/oauth/authorize",
        data={"state_token": state_token, "decision": decision},
        follow_redirects=False,
    )
    assert post_r.status_code == 302
    location = urlparse(post_r.headers["location"])
    assert location._replace(query="").geturl() == "http://localhost:9000/callback"
    qs = parse_qs(location.query, keep_blank_values=True)
    assert qs["state"] == [upstream_state]
    if decision == "allow":
        assert set(qs) == {"code", "state"}
        assert qs["code"][0]
    else:
        assert qs == {"error": ["access_denied"], "state": [upstream_state]}


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
