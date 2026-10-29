"""Redirect URI checks: the loopback port is the only part allowed to vary, and
dynamic clients register only HTTPS, loopback HTTP or app-scheme callbacks."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models import OAuthClient
from app.oauth.clients import registrable_redirect_uri, validate_redirect_uri
from tests.conftest import login_as, make_pkce, mk_user, resource_uri

LOOPBACK = SimpleNamespace(redirect_uris=["http://127.0.0.1:*/callback"], is_dynamic=False)


@pytest.mark.parametrize("uri", ["http://127.0.0.1:49152/callback", "http://127.0.0.1:1/callback"])
def test_loopback_pattern_accepts_any_port(uri):
    assert validate_redirect_uri(LOOPBACK, uri)


@pytest.mark.parametrize(
    "uri",
    [
        "http://127.0.0.1:49152@outside.example/callback",
        "http://user:pass@127.0.0.1:49152/callback",
        "http://127.0.0.1:49152\\@outside.example/callback",
        "http://127.0.0.1:49152/callback\n",
        "http://127.0.0.1:49152/call\tback",
        "http://127.0.0.1.outside.example:49152/callback",
        "http://localhost:49152/callback",
        "https://127.0.0.1:49152/callback",
        "http://127.0.0.1/callback",
        "http://127.0.0.1:0/callback",
        "http://127.0.0.1:65536/callback",
        "http://127.0.0.1:x/callback",
        "http://127.0.0.1:49152/callback?next=/",
        "http://127.0.0.1:49152/callback#frag",
        "http://127.0.0.1:49152/other",
        "http://127.0.0.1:49152/callback/../callback",
    ],
)
def test_loopback_pattern_rejects_anything_but_the_port(uri):
    assert not validate_redirect_uri(LOOPBACK, uri)


def test_a_dynamic_client_gets_no_port_wildcard():
    dynamic = SimpleNamespace(redirect_uris=["http://127.0.0.1:*/callback"], is_dynamic=True)
    assert not validate_redirect_uri(dynamic, "http://127.0.0.1:49152/callback")
    assert validate_redirect_uri(dynamic, "http://127.0.0.1:*/callback")


@pytest.mark.parametrize(
    "uri",
    [
        "https://chatgpt.com/connector_platform_oauth_redirect",
        "https://claude.ai/api/mcp/oauth/callback",
        "http://localhost:9000/callback",
        "http://127.0.0.1:33418/callback",
        "http://[::1]:8080/callback",
        "cursor://anysphere.cursor-mcp/oauth/callback",
        "com.example.app:/oauth/callback",
    ],
)
def test_registration_accepts_https_loopback_http_and_app_schemes(uri):
    assert registrable_redirect_uri(uri)


@pytest.mark.parametrize(
    "uri",
    [
        "http://outside.example/callback",
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        "https://user:pass@outside.example/callback",
        "https://outside.example/callback#frag",
        "http://127.0.0.1:*/callback",
        "https://outside.example\\@localhost/callback",
        "/relative/callback",
        "https://outside.example:99999/callback",
        42,
    ],
)
def test_registration_rejects_other_callbacks(uri):
    assert not registrable_redirect_uri(uri)


@pytest.mark.asyncio
async def test_dcr_rejects_an_unsafe_redirect_uri(client):
    r = await client.post(
        "/api/auth/oauth/register",
        json={"client_name": "X", "redirect_uris": ["http://outside.example/callback"]},
    )
    assert r.status_code == 400
    assert r.json()["code"] == "invalid_redirect_uri"


async def _authorize(client, client_id, redirect_uri):
    _, challenge = make_pkce()
    return await client.get(
        "/api/auth/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": "ics",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "resource": resource_uri(),
        },
    )


@pytest.mark.asyncio
async def test_stdio_client_consent_shows_where_the_code_goes(client, session):
    # Built like the seeded stdio client, under its own id: other tests may
    # have seeded the real one in this database already.
    client_id = f"stdio-{uuid4().hex[:8]}"
    session.add(
        OAuthClient(
            client_id=client_id,
            name="MCP stdio",
            client_type="public",
            redirect_uris=["http://127.0.0.1:*/callback"],
            allowed_scopes=["ics"],
            allowed_audiences=[resource_uri()],
        )
    )
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)

    rejected = await _authorize(
        client, client_id, "http://127.0.0.1:49152@outside.example/callback"
    )
    assert rejected.status_code == 400
    assert rejected.json()["code"] == "invalid_redirect_uri"

    consent = await _authorize(client, client_id, "http://127.0.0.1:49152/callback")
    assert consent.status_code == 200
    assert "<code>http://127.0.0.1:49152</code>" in consent.text
