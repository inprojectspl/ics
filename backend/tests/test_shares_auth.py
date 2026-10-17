"""Tests for `routes/shares/auth.py`: share info, password challenge, magic-link claim.

The magic-link claim is a security path: the signed payload binds one share
to one e-mail, so every rejection test also checks that the browser session
did not get the share marked as verified.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from itsdangerous import TimestampSigner, URLSafeTimedSerializer
from sqlalchemy import select

from app import tokens
from app.models import ShareLink
from app.routes.shares._shared import _magic_payload
from tests.conftest import login_as as _login
from tests.conftest import mk_asset, mk_user


async def _create_share(client, session, owner, **body):
    """Owner creates a share through the API; returns the ShareLink row."""
    asset = await mk_asset(session, owner)
    await session.commit()
    await _login(client, owner)
    r = await client.post(f"/api/assets/{asset.id}/shares", json=body)
    assert r.status_code == 201, r.text
    await client.post("/api/auth/logout")
    return await session.scalar(select(ShareLink).where(ShareLink.id == r.json()["id"]))


async def _create_magic_share(client, session, owner, allowed_emails: list[str]):
    return await _create_share(
        client, session, owner, mode="magic_email", allowed_emails=allowed_emails
    )


async def _claim(client, share, magic_token: str):
    return await client.post(f"/api/share/{share.token}/magic-claim", json={"m": magic_token})


async def _assert_no_access(client, share) -> None:
    info = await client.get(f"/api/share/{share.token}/info")
    assert info.status_code == 200
    assert info.json()["has_access"] is False
    assert info.json()["requires_magic_link"] is True


@pytest.mark.asyncio
async def test_info_for_asset_owner_skips_challenge_and_exposes_slug(client, session):
    owner = await mk_user(session)
    share = await _create_share(client, session, owner, mode="password", password="Secret-Pass-1!")
    await _login(client, owner)

    r = await client.get(f"/api/share/{share.token}/info")
    assert r.status_code == 200
    body = r.json()
    assert body["has_access"] is True
    assert body["requires_password"] is False
    assert body["my_role"] is not None
    assert body["slug"] is not None


@pytest.mark.asyncio
async def test_info_for_magic_share_requires_magic_link(client, session):
    owner = await mk_user(session)
    share = await _create_magic_share(client, session, owner, ["someone@example.com"])
    await _assert_no_access(client, share)


@pytest.mark.asyncio
async def test_password_auth_on_non_password_share_returns_400(client, session):
    owner = await mk_user(session)
    share = await _create_share(client, session, owner, mode="public")

    r = await client.post(f"/api/share/{share.token}/auth", json={"password": "whatever"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_magic_claim_happy_path_marks_verified(client, session):
    owner = await mk_user(session)
    share = await _create_magic_share(client, session, owner, ["recipient@example.com"])

    magic_token = tokens.issue("magic_link", _magic_payload(share.id, "recipient@example.com"))
    r = await _claim(client, share, magic_token)
    assert r.status_code == 200
    assert r.json() == {"ok": True, "email": "recipient@example.com"}

    info = await client.get(f"/api/share/{share.token}/info")
    assert info.json()["has_access"] is True
    assert info.json()["requires_magic_link"] is False


@pytest.mark.asyncio
async def test_magic_claim_rejects_wrong_share_mode(client, session):
    """A public share does not use magic links, so the claim is refused."""
    owner = await mk_user(session)
    share = await _create_share(client, session, owner, mode="public")

    r = await _claim(client, share, "garbage.token")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_magic_claim_with_invalid_token_returns_400(client, session):
    owner = await mk_user(session)
    share = await _create_magic_share(client, session, owner, ["x@example.com"])

    r = await _claim(client, share, "this-is-not-a-real-token")
    assert r.status_code == 400
    await _assert_no_access(client, share)


@pytest.mark.asyncio
async def test_magic_claim_with_expired_token_returns_400(client, session):
    owner = await mk_user(session)
    share = await _create_magic_share(client, session, owner, ["late@example.com"])
    # Backdate the issue time instead of patching "now" during the request:
    # the session cookie signer uses the same itsdangerous clock.
    issued_at = int(time.time()) - tokens.TTL["magic_link"] - 60
    with patch.object(TimestampSigner, "get_timestamp", return_value=issued_at):
        magic_token = tokens.issue("magic_link", _magic_payload(share.id, "late@example.com"))
    with pytest.raises(tokens.TokenExpired):
        tokens.verify("magic_link", magic_token)

    r = await _claim(client, share, magic_token)
    assert r.status_code == 400
    await _assert_no_access(client, share)


@pytest.mark.asyncio
async def test_magic_claim_with_foreign_secret_signature_returns_400(client, session):
    """A payload signed with another secret key must not verify."""
    owner = await mk_user(session)
    share = await _create_magic_share(client, session, owner, ["target@example.com"])
    forged = URLSafeTimedSerializer("not-the-server-secret").dumps(
        _magic_payload(share.id, "target@example.com"), salt="magic_link"
    )

    r = await _claim(client, share, forged)
    assert r.status_code == 400
    await _assert_no_access(client, share)


@pytest.mark.asyncio
async def test_magic_claim_with_other_purpose_token_returns_400(client, session):
    """A token signed by the server for another purpose (salt) is rejected."""
    owner = await mk_user(session)
    share = await _create_magic_share(client, session, owner, ["target@example.com"])
    invite_token = tokens.issue("invite", _magic_payload(share.id, "target@example.com"))

    r = await _claim(client, share, invite_token)
    assert r.status_code == 400
    await _assert_no_access(client, share)


@pytest.mark.asyncio
async def test_magic_claim_with_malformed_payload_returns_400(client, session):
    owner = await mk_user(session)
    share = await _create_magic_share(client, session, owner, ["target@example.com"])
    magic_token = tokens.issue("magic_link", "not-a-uuid|target@example.com")

    r = await _claim(client, share, magic_token)
    assert r.status_code == 400
    await _assert_no_access(client, share)


@pytest.mark.asyncio
async def test_magic_claim_email_not_in_allowlist_returns_403(client, session):
    """Token signed for the right share but an e-mail outside the recipient list."""
    owner = await mk_user(session)
    share = await _create_magic_share(client, session, owner, ["intended@example.com"])
    magic_token = tokens.issue("magic_link", _magic_payload(share.id, "interloper@example.com"))

    r = await _claim(client, share, magic_token)
    assert r.status_code == 403
    await _assert_no_access(client, share)


@pytest.mark.asyncio
async def test_magic_claim_on_share_with_empty_allowlist_returns_403(client, session):
    owner = await mk_user(session)
    share = await _create_magic_share(client, session, owner, ["gone@example.com"])
    share.allowed_emails = []
    await session.commit()
    magic_token = tokens.issue("magic_link", _magic_payload(share.id, "gone@example.com"))

    r = await _claim(client, share, magic_token)
    assert r.status_code == 403
    await _assert_no_access(client, share)


@pytest.mark.asyncio
async def test_magic_claim_token_for_other_share_returns_400(client, session):
    """A token issued for another share does not unlock this one, even when
    the e-mail is on this share's allow-list."""
    owner = await mk_user(session)
    share = await _create_magic_share(client, session, owner, ["a@example.com"])
    other_share = await _create_magic_share(client, session, owner, ["a@example.com"])
    magic_token = tokens.issue("magic_link", _magic_payload(other_share.id, "a@example.com"))

    r = await _claim(client, share, magic_token)
    assert r.status_code == 400
    await _assert_no_access(client, share)
