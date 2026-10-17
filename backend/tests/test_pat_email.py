"""Creating a personal access token e-mails a notice to its owner (ADR-0020)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.i18n import t
from app.models import EmailOutbox
from tests.conftest import login_as, mk_user


def _expiry() -> str:
    return (datetime.now(UTC) + timedelta(days=30)).isoformat()


async def _outbox_for(session, email: str) -> list[EmailOutbox]:
    rows = await session.scalars(select(EmailOutbox).where(EmailOutbox.to_email == email))
    return list(rows.all())


@pytest.mark.parametrize("locale", ["pl", "en"])
async def test_creating_a_token_enqueues_one_email_in_the_owner_locale(client, session, locale):
    user = await mk_user(session, locale=locale)
    await session.commit()
    await login_as(client, user)

    # The request language loses to the owner's stored choice.
    other = "en" if locale == "pl" else "pl"
    r = await client.post(
        "/api/auth/tokens",
        json={"name": "claude-code", "expires_at": _expiry()},
        headers={"Accept-Language": other},
    )
    assert r.status_code == 201
    created = r.json()

    rows = await _outbox_for(session, user.email)
    assert len(rows) == 1
    mail = rows[0]
    assert mail.purpose == "notification"
    assert mail.subject == t("email.token.subject", locale)
    assert created["prefix"] in mail.body
    assert "claude-code" in mail.body
    # The notice never carries the secret itself.
    assert created["token"] not in mail.body
    assert mail.body_html is not None
    assert created["token"] not in mail.body_html


async def test_request_language_applies_when_the_owner_has_no_locale(client, session):
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)

    r = await client.post(
        "/api/auth/tokens",
        json={"name": "ci", "expires_at": _expiry()},
        headers={"Accept-Language": "pl-PL,pl;q=0.9"},
    )
    assert r.status_code == 201
    rows = await _outbox_for(session, user.email)
    assert [m.subject for m in rows] == [t("email.token.subject", "pl")]


async def test_refused_token_sends_no_email(client, session):
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)

    r = await client.post(
        "/api/auth/tokens",
        json={"name": "ci", "expires_at": (datetime.now(UTC) + timedelta(days=365)).isoformat()},
    )
    assert r.status_code == 400
    assert await _outbox_for(session, user.email) == []
