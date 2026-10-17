"""Personal access tokens (ADR-0020): issuing limits, verification of expired
and revoked tokens, hashed storage, and revocation on account lock."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text, update

from app.domain_errors import DomainError
from app.errors import domain_status
from app.models import AuditLog, PersonalAccessToken
from app.routes.admin_users import LockIn, lock_user
from app.services import pat
from tests.conftest import login_as, mk_admin, mk_user


def _in_days(days: float) -> datetime:
    return datetime.now(UTC) + timedelta(days=days)


async def test_sixth_active_token_is_refused(session):
    user = await mk_user(session)
    for i in range(pat.MAX_ACTIVE_TOKENS):
        await pat.create(session, user=user, name=f"t{i}", expires_at=_in_days(30))

    with pytest.raises(DomainError) as exc:
        await pat.create(session, user=user, name="sixth", expires_at=_in_days(30))
    assert exc.value.code == "pat_limit"
    assert domain_status(exc.value) == 413


async def test_revoked_and_expired_tokens_do_not_count_against_the_limit(session):
    user = await mk_user(session)
    tokens = [
        (await pat.create(session, user=user, name=f"t{i}", expires_at=_in_days(30)))[0]
        for i in range(pat.MAX_ACTIVE_TOKENS)
    ]
    await pat.revoke(session, token_id=tokens[0].id, user_id=user.id, actor=user)
    tokens[1].expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.flush()

    await pat.create(session, user=user, name="a", expires_at=_in_days(30))
    await pat.create(session, user=user, name="b", expires_at=_in_days(30))


@pytest.mark.parametrize("days", [0, -1, 181])
async def test_expiry_must_be_within_180_days(session, days):
    user = await mk_user(session)
    with pytest.raises(DomainError) as exc:
        await pat.create(session, user=user, name="t", expires_at=_in_days(days))
    assert exc.value.code == "pat_expiry_invalid"
    assert domain_status(exc.value) == 400


async def test_valid_token_verifies_and_records_use(session):
    user = await mk_user(session)
    token, plaintext = await pat.create(session, user=user, name="ps", expires_at=_in_days(90))
    assert plaintext.startswith(f"ics_pat_{token.token_prefix}_")

    found = await pat.verify(session, plaintext)
    assert found is not None and found.id == token.id
    assert found.scopes == ["ics:read"]
    assert await pat.record_use(session, found) is True
    assert found.last_used_at is not None


async def test_last_used_is_written_at_most_once_per_resolution(session):
    """A token used in a loop must not write its row on every request."""
    user = await mk_user(session)
    token, _ = await pat.create(session, user=user, name="ps", expires_at=_in_days(90))
    await session.commit()

    assert await pat.record_use(session, token) is True
    first = token.last_used_at
    assert await pat.record_use(session, token) is False
    assert token.last_used_at == first

    # Another request already stamped the row: the conditional UPDATE is a no-op.
    token.last_used_at = None
    await session.flush()
    await session.execute(
        update(PersonalAccessToken)
        .where(PersonalAccessToken.id == token.id)
        .values(last_used_at=datetime.now(UTC))
    )
    assert await pat.record_use(session, token) is False

    stale = datetime.now(UTC) - pat.LAST_USED_RESOLUTION - timedelta(seconds=1)
    await session.execute(
        update(PersonalAccessToken)
        .where(PersonalAccessToken.id == token.id)
        .values(last_used_at=stale)
    )
    await session.refresh(token)
    assert await pat.record_use(session, token) is True
    assert token.last_used_at is not None and token.last_used_at > stale


async def test_tampered_or_malformed_tokens_fail(session):
    user = await mk_user(session)
    _, plaintext = await pat.create(session, user=user, name="ps", expires_at=_in_days(90))

    for bad in (plaintext[:-1] + ("A" if plaintext[-1] != "A" else "B"), "ics_pat_zz_x", "", "x"):
        assert await pat.verify(session, bad) is None


async def test_expired_token_fails_verification(session):
    user = await mk_user(session)
    token, plaintext = await pat.create(session, user=user, name="ps", expires_at=_in_days(1))
    token.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.flush()

    assert await pat.verify(session, plaintext) is None


async def test_revoked_token_fails_verification(session):
    user = await mk_user(session)
    token, plaintext = await pat.create(session, user=user, name="ps", expires_at=_in_days(1))
    await pat.revoke(session, token_id=token.id, user_id=user.id, actor=user)

    assert await pat.verify(session, plaintext) is None


async def test_no_plaintext_secret_is_stored(session):
    user = await mk_user(session)
    token, plaintext = await pat.create(session, user=user, name="ps", expires_at=_in_days(1))
    await session.commit()

    # The random part may itself contain "_", so split after the prefix.
    secret = plaintext.removeprefix(pat.TOKEN_PREFIX).partition("_")[2]
    row = (
        await session.execute(
            text("SELECT * FROM personal_access_tokens WHERE id = :id"), {"id": token.id}
        )
    ).one()
    stored = " ".join(str(v) for v in row)
    assert secret not in stored
    assert plaintext not in stored
    assert row.token_hash == pat.hash_token(plaintext)


async def test_locking_the_account_revokes_all_tokens(session):
    admin = await mk_admin(session)
    user = await mk_user(session)
    issued = [
        (await pat.create(session, user=user, name=f"t{i}", expires_at=_in_days(30)))[1]
        for i in range(3)
    ]

    await lock_user(user.id, LockIn(minutes=30), admin, session)

    for plaintext in issued:
        assert await pat.verify(session, plaintext) is None
    rows = (
        await session.scalars(
            select(PersonalAccessToken).where(PersonalAccessToken.user_id == user.id)
        )
    ).all()
    assert rows and all(r.revoked_at is not None for r in rows)
    audit = await session.scalar(
        select(AuditLog).where(
            AuditLog.action == "pat_revoked", AuditLog.target == f"user:{user.id}"
        )
    )
    assert audit is not None and audit.payload["reason"] == "account_locked"


async def test_token_api_round_trip(client, session):
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)

    r = await client.post(
        "/api/auth/tokens", json={"name": "ps", "expires_at": _in_days(30).isoformat()}
    )
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["token"].startswith("ics_pat_")

    r = await client.get("/api/auth/tokens")
    assert r.status_code == 200
    items = r.json()["items"]
    assert [i["id"] for i in items] == [created["id"]]
    assert "token" not in items[0]

    r = await client.post(
        "/api/auth/tokens", json={"name": "ps", "expires_at": _in_days(365).isoformat()}
    )
    assert r.status_code == 400
    assert r.json()["code"] == "pat_expiry_invalid"

    r = await client.delete(f"/api/auth/tokens/{created['id']}")
    assert r.status_code == 204
    assert (await client.get("/api/auth/tokens")).json()["items"] == []


async def test_user_cannot_revoke_someone_elses_token(client, session):
    owner = await mk_user(session)
    other = await mk_user(session)
    token, _ = await pat.create(session, user=owner, name="ps", expires_at=_in_days(30))
    await session.commit()
    await login_as(client, other)

    r = await client.delete(f"/api/auth/tokens/{token.id}")
    assert r.status_code == 404
    assert r.json()["code"] == "pat_not_found"


async def test_admin_revokes_all_tokens_of_a_user(client, session):
    admin = await mk_admin(session)
    user = await mk_user(session)
    for i in range(2):
        await pat.create(session, user=user, name=f"t{i}", expires_at=_in_days(30))
    await session.commit()

    await login_as(client, user)
    r = await client.post(f"/api/admin/users/{user.id}/tokens/revoke")
    assert r.status_code == 403

    await login_as(client, admin)
    r = await client.post(f"/api/admin/users/{user.id}/tokens/revoke")
    assert r.status_code == 200
    assert r.json() == {"revoked": 2}
