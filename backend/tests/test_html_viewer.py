"""HTML viewer subdomain: grant token + access cookie + redirect target."""

import time
from unittest.mock import patch
from uuid import uuid4

import pytest
from itsdangerous.timed import TimestampSigner

from app import tokens
from app.routes.html_viewer import (
    COOKIE_NAME,
    _read_granted,
    _sign_granted,
    issue_grant,
)


class _FakeRequest:
    def __init__(self, cookies: dict[str, str] | None = None) -> None:
        self.cookies = cookies or {}


# ---------- grant token ----------


def test_grant_token_roundtrip():
    aid = uuid4()
    t = issue_grant(aid)
    payload = tokens.verify("html_grant", t)
    assert payload == str(aid)


def test_grant_token_purpose_isolation():
    """A grant token must not be accepted as a reset/invite token."""
    t = issue_grant(uuid4())
    with pytest.raises(tokens.TokenInvalid):
        tokens.verify("reset", t)
    with pytest.raises(tokens.TokenInvalid):
        tokens.verify("invite", t)


def test_grant_token_expires():
    with patch.dict(tokens.TTL, {"html_grant": 1}):
        t = issue_grant(uuid4())
        future = int(time.time()) + 5
        with patch.object(TimestampSigner, "get_timestamp", return_value=future):
            with pytest.raises(tokens.TokenExpired):
                tokens.verify("html_grant", t)


# ---------- access cookie ----------


def test_cookie_roundtrip_single_id():
    aid = str(uuid4())
    value = _sign_granted({aid})
    assert _read_granted(_FakeRequest({COOKIE_NAME: value})) == {aid}


def test_cookie_roundtrip_multiple_ids():
    ids = {str(uuid4()) for _ in range(3)}
    value = _sign_granted(ids)
    assert _read_granted(_FakeRequest({COOKIE_NAME: value})) == ids


def test_cookie_missing_returns_empty():
    assert _read_granted(_FakeRequest({})) == set()


def test_cookie_tampered_returns_empty():
    aid = str(uuid4())
    value = _sign_granted({aid})
    # flip a byte in the middle of the signature
    tampered = value[:-3] + ("AA" if value[-3:] != "AAA" else "BBB")
    assert _read_granted(_FakeRequest({COOKIE_NAME: tampered})) == set()


def test_cookie_signed_with_wrong_purpose_rejected():
    """A token signed under another purpose must not unlock html access."""
    misuse = tokens.issue("reset", str(uuid4()))
    assert _read_granted(_FakeRequest({COOKIE_NAME: misuse})) == set()


# ---------- /_/grant integration ----------


@pytest.mark.asyncio
async def test_grant_with_invalid_token_returns_400(client):
    r = await client.get("/html/_/grant?t=not-a-real-token", follow_redirects=False)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_grant_for_nonexistent_asset_returns_404(client):
    # Token signed correctly but for a nonexistent UUID.
    token = tokens.issue("html_grant", "11111111-2222-3333-4444-555555555555")
    r = await client.get(f"/html/_/grant?t={token}", follow_redirects=False)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_grant_rejects_md_asset_token(client, session):
    """Token points at an md_single: `kind != html_bundle` -> 404."""
    from tests.conftest import mk_asset, mk_user

    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="md_single")
    await session.commit()
    token = issue_grant(asset.id)

    r = await client.get(f"/html/_/grant?t={token}", follow_redirects=False)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_grant_for_html_bundle_redirects_and_sets_cookie(client, session):
    from tests.conftest import mk_asset, mk_user

    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="html_bundle", entry_path="index.html")
    await session.commit()
    token = issue_grant(asset.id)

    r = await client.get(f"/html/_/grant?t={token}", follow_redirects=False)
    assert r.status_code == 302
    location = r.headers.get("location", "")
    assert f"/{asset.slug}/index.html" in location
    set_cookie = r.headers.get("set-cookie", "")
    assert "ics_html_access" in set_cookie


# ---------- /{slug}/{path} integration ----------


@pytest.mark.asyncio
async def test_serve_without_cookie_returns_401(client, session):
    from tests.conftest import mk_asset, mk_user

    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="html_bundle", entry_path="index.html")
    await session.commit()

    r = await client.get(f"/html/{asset.slug}/index.html")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_serve_404_for_unknown_slug(client):
    r = await client.get("/html/nonexistent-slug-xyz/anything.html")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_serve_404_for_md_asset(client, session):
    from tests.conftest import mk_asset, mk_user

    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="md_single")
    await session.commit()

    r = await client.get(f"/html/{asset.slug}/anything")
    assert r.status_code == 404


# ---------- archived version preview: /-v{n}/{slug}/{path} ----------


async def _bundle_with_two_versions(session):
    """v1: index.html + app.css; v2: index.html (different content)."""
    from tests.conftest import mk_asset, mk_user, put_blob

    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="html_bundle", entry_path="index.html")
    await put_blob(asset, "index.html", b"<html><body><h1>Old version</h1></body></html>")
    await put_blob(asset, "app.css", b"body{color:red}")
    asset.version = 2
    await session.commit()
    await put_blob(asset, "index.html", b"<html><body><h1>New version</h1></body></html>")
    return asset


async def _grant_cookie(client, asset, version=None):
    token = issue_grant(asset.id, version=version)
    r = await client.get(f"/html/_/grant?t={token}", follow_redirects=False)
    return r


def test_grant_token_carries_version():
    aid = uuid4()
    assert tokens.verify("html_grant", issue_grant(aid, version=3)) == f"{aid}:3"
    # The current version stays a bare UUID, matching the shape of old tokens.
    assert tokens.verify("html_grant", issue_grant(aid)) == str(aid)


@pytest.mark.asyncio
async def test_grant_with_version_redirects_to_versioned_prefix(client, session, fs_storage):
    asset = await _bundle_with_two_versions(session)

    r = await _grant_cookie(client, asset, version=1)
    assert r.status_code == 302
    assert f"/-v1/{asset.slug}/index.html" in r.headers.get("location", "")


@pytest.mark.asyncio
async def test_grant_rejects_version_out_of_range(client, session, fs_storage):
    asset = await _bundle_with_two_versions(session)
    token = issue_grant(asset.id, version=99)

    r = await client.get(f"/html/_/grant?t={token}", follow_redirects=False)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_versioned_serve_requires_matching_grant(client, session, fs_storage):
    """A grant for the current version does not open the archive (and vice
    versa): cookie entry keys are separate, so an old token gives no access
    to the history."""
    asset = await _bundle_with_two_versions(session)
    await _grant_cookie(client, asset)  # grant for the current version only

    r = await client.get(f"/html/-v1/{asset.slug}/index.html")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_versioned_serve_returns_archived_html_with_banner(client, session, fs_storage):
    asset = await _bundle_with_two_versions(session)
    await _grant_cookie(client, asset, version=1)

    r = await client.get(f"/html/-v1/{asset.slug}/index.html")
    assert r.status_code == 200
    body = r.text
    assert "Old version" in body
    assert "New version" not in body
    assert "ics-version-banner" in body
    # The banner must not float: a static block in normal flow.
    assert "position:fixed" not in body
    # No Accept-Language: English.
    assert "You are viewing archived version v1" in body


@pytest.mark.asyncio
async def test_versioned_serve_banner_follows_accept_language(client, session, fs_storage):
    asset = await _bundle_with_two_versions(session)
    await _grant_cookie(client, asset, version=1)

    r = await client.get(
        f"/html/-v1/{asset.slug}/index.html", headers={"Accept-Language": "pl-PL,pl;q=0.9"}
    )
    assert r.status_code == 200
    assert "Podgl&#261;dasz archiwaln&#261; wersj&#281; v1" in r.text


@pytest.mark.asyncio
async def test_versioned_serve_leaves_non_html_untouched(client, session, fs_storage):
    asset = await _bundle_with_two_versions(session)
    await _grant_cookie(client, asset, version=1)

    r = await client.get(f"/html/-v1/{asset.slug}/app.css")
    assert r.status_code == 200
    assert r.content == b"body{color:red}"


@pytest.mark.asyncio
async def test_current_version_serve_has_no_banner(client, session, fs_storage):
    asset = await _bundle_with_two_versions(session)
    await _grant_cookie(client, asset)

    r = await client.get(f"/html/{asset.slug}/index.html")
    assert r.status_code == 200
    assert "New version" in r.text
    assert "ics-version-banner" not in r.text


@pytest.mark.asyncio
async def test_versioned_serve_gated_for_critical_bundle(client, session, fs_storage):
    """The security scan covers the document, not a single version: critical
    without a bypass also blocks the history."""
    asset = await _bundle_with_two_versions(session)
    await _grant_cookie(client, asset, version=1)
    asset.security_status = "critical"
    asset.security_bypass = False
    await session.commit()

    r = await client.get(f"/html/-v1/{asset.slug}/index.html")
    assert r.status_code == 410
