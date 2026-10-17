"""Mail outbox: persists to DB always, attempts SMTP delivery only when
configured, marks sent_at on success, swallows SMTP errors so the
caller's HTTP request never breaks."""

from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import email_outbox
from app.config import get_settings
from app.db import Base
from app.models import EmailOutbox


@pytest_asyncio.fixture
async def session():
    settings = get_settings()
    engine = create_async_engine(settings.database_url, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


def _cfg(smtp_host: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        smtp_host=smtp_host,
        smtp_port=1025,
        smtp_from="ICS <no-reply@ics.test>",
        smtp_user="",
        smtp_password="",
        smtp_use_tls=False,
    )


# ---------- DB persistence (always) ----------


@pytest.mark.asyncio
async def test_persists_to_db_without_smtp(session):
    await email_outbox.queue_email(
        session,
        to_email="a@example.com",
        subject="x",
        body="y",
        purpose="invite",
        settings=_cfg(""),
    )
    await session.commit()
    rows = (await session.execute(select(EmailOutbox))).scalars().all()
    target = [r for r in rows if r.to_email == "a@example.com" and r.subject == "x"]
    assert target and target[0].sent_at is None


# ---------- SMTP delivery (when host configured) ----------


@pytest.mark.asyncio
async def test_sends_via_smtp_and_marks_sent(session, monkeypatch):
    calls = []

    async def fake_send(message, **kwargs):
        calls.append(
            {
                "to": message["To"],
                "subject": message["Subject"],
                "hostname": kwargs.get("hostname"),
                "port": kwargs.get("port"),
            }
        )

    monkeypatch.setattr(email_outbox.aiosmtplib, "send", fake_send)

    await email_outbox.queue_email(
        session,
        to_email="b@example.com",
        subject="hello",
        body="world",
        purpose="invite",
        settings=_cfg("mailpit"),
    )
    await session.commit()

    assert len(calls) == 1
    assert calls[0]["to"] == "b@example.com"
    assert calls[0]["hostname"] == "mailpit"
    assert calls[0]["port"] == 1025

    rows = (
        (await session.execute(select(EmailOutbox).where(EmailOutbox.to_email == "b@example.com")))
        .scalars()
        .all()
    )
    assert rows and rows[0].sent_at is not None


@pytest.mark.asyncio
async def test_swallows_smtp_failure_and_keeps_row_unsent(session, monkeypatch):
    async def boom(message, **kwargs):
        raise ConnectionRefusedError("dev mailpit not running")

    monkeypatch.setattr(email_outbox.aiosmtplib, "send", boom)

    # Must not raise: SMTP errors are deliberately swallowed.
    await email_outbox.queue_email(
        session,
        to_email="c@example.com",
        subject="x",
        body="y",
        purpose="reset",
        settings=_cfg("mailpit"),
    )
    await session.commit()

    rows = (
        (await session.execute(select(EmailOutbox).where(EmailOutbox.to_email == "c@example.com")))
        .scalars()
        .all()
    )
    # Row stays, sent_at stays None, so a retry worker or an admin sees it.
    assert rows and rows[0].sent_at is None
