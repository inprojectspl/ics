"""Outgoing email: always stored in `email_outbox`, then sent over SMTP when
`ICS_SMTP_HOST` is set. SMTP failures are logged and the row stays unsent for a
replay.
"""

from __future__ import annotations

import logging
from email.message import EmailMessage
from email.policy import SMTP

import aiosmtplib
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.constants import EmailPurpose
from app.models import EmailOutbox
from app.util import now as utc_now

logger = logging.getLogger("ics.email")

_SMTP_TIMEOUT_SECONDS = 5.0
# RFC 5322 allows 998 characters per line. With the default 78 a long URL in
# `List-Unsubscribe` becomes an RFC 2047 encoded word, which mail clients do
# not read as a link, so one-click unsubscribe would silently stop working.
_POLICY = SMTP.clone(max_line_length=998)


async def queue_email(
    session: AsyncSession,
    to_email: str,
    subject: str,
    body: str,
    purpose: EmailPurpose,
    body_html: str | None = None,
    settings: Settings | None = None,
    list_unsubscribe_url: str | None = None,
) -> None:
    """Persist to DB and (best-effort) deliver via SMTP; with `body_html` the
    message is multipart/alternative, plain text first."""
    cfg = settings or get_settings()
    row = EmailOutbox(
        to_email=to_email,
        subject=subject,
        body=body,
        body_html=body_html,
        purpose=purpose,
    )
    session.add(row)
    await session.flush()

    if not cfg.smtp_host:
        return

    try:
        message = _build_message(
            to_email=to_email,
            subject=subject,
            body=body,
            body_html=body_html,
            smtp_from=cfg.smtp_from,
            list_unsubscribe_url=list_unsubscribe_url,
        )
        await aiosmtplib.send(
            message,
            hostname=cfg.smtp_host,
            port=cfg.smtp_port,
            username=cfg.smtp_user or None,
            password=cfg.smtp_password or None,
            use_tls=cfg.smtp_use_tls,
            timeout=_SMTP_TIMEOUT_SECONDS,
        )
        row.sent_at = utc_now()
    except Exception as e:
        logger.warning(
            "SMTP send failed (mail stays in DB): to=%s purpose=%s err=%s",
            to_email,
            purpose,
            e,
        )


def _build_message(
    *,
    to_email: str,
    subject: str,
    body: str,
    body_html: str | None,
    smtp_from: str,
    list_unsubscribe_url: str | None = None,
) -> EmailMessage:
    msg = EmailMessage(policy=_POLICY)
    msg["From"] = smtp_from
    msg["To"] = to_email
    msg["Subject"] = subject
    if list_unsubscribe_url:
        # One-click unsubscribe (RFC 8058): mail clients POST to the URL.
        msg["List-Unsubscribe"] = f"<{list_unsubscribe_url}>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.set_content(body)
    if body_html:
        msg.add_alternative(body_html, subtype="html")
    return msg
