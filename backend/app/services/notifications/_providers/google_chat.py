"""Google Chat incoming webhook: Cards v2 with a link to the asset.

The URL is host-locked to `chat.googleapis.com` (there is no self-hosted Google
Chat), which keeps the SSRF surface to a single public host.
"""

from __future__ import annotations

import logging
from typing import ClassVar, Final, override

import httpx

from app.i18n import t, tn
from app.util import is_host_locked_https

from .._types import (
    NotificationContext,
    NotificationProviderId,
)
from ._base import NotificationProvider

logger = logging.getLogger("ics.notifications.google_chat")

_ALLOWED_HOSTS: Final[frozenset[str]] = frozenset({"chat.googleapis.com"})
_TIMEOUT_SECONDS: Final[float] = 3.0
_MAX_TITLE_LEN: Final[int] = 200


class GoogleChatProvider(NotificationProvider):
    id: ClassVar[NotificationProviderId] = NotificationProviderId.GOOGLE_CHAT
    display_name: ClassVar[str] = "Google Chat"
    url_hint: ClassVar[str] = "https://chat.googleapis.com/v1/spaces/AAA/messages?key=...&token=..."

    @override
    def accepts_url(self, url: str) -> bool:
        return is_host_locked_https(url, _ALLOWED_HOSTS)

    @override
    async def send(self, url: str, ctx: NotificationContext) -> None:
        await self.post(url, self._build_card(ctx))

    async def post(self, url: str, payload: dict[str, object]) -> int | None:
        """POST a message; the HTTP status, or None when the request failed.
        Never raises, and never logs the URL (it carries the webhook key).
        The host check repeats the DTO validation on purpose: a row edited
        by hand in the database must not turn this into a POST anywhere."""
        if not self.accepts_url(url):
            logger.warning("rejected non-google-chat url")
            return None
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                r = await client.post(url, json=payload)
        except Exception as e:
            logger.warning("google_chat POST failed: %s", type(e).__name__)
            return None
        if r.status_code >= 400:
            logger.warning(
                "google_chat non-2xx: status=%s body=%s",
                r.status_code,
                r.text[:200],
            )
        return r.status_code

    @staticmethod
    def _build_card(ctx: NotificationContext) -> dict[str, object]:
        loc = ctx.locale
        title = (ctx.asset_title or ctx.asset_slug)[:_MAX_TITLE_LEN]
        files = tn("chat.files", ctx.file_count, loc)
        widgets: list[dict[str, object]] = [
            {
                "decoratedText": {
                    "topLabel": t("chat.version", loc),
                    "text": f"<b>v{ctx.version}</b> · {files}",
                }
            },
            {
                "decoratedText": {
                    "topLabel": t("chat.commit", loc),
                    "text": ctx.commit_sha[:8] if ctx.commit_sha else "-",
                }
            },
        ]
        if ctx.security_status and ctx.security_status != "clean":
            status_label = t(f"chat.security_status.{ctx.security_status}", loc)
            widgets.append(
                {
                    "decoratedText": {
                        "topLabel": t("chat.security_scan", loc),
                        "text": f"⚠ {status_label}",
                    }
                }
            )
        widgets.append(
            {
                "buttonList": {
                    "buttons": [
                        {
                            "text": t("chat.open", loc),
                            "onClick": {"openLink": {"url": ctx.link.url}},
                        }
                    ]
                }
            }
        )
        return {
            "cardsV2": [
                {
                    "cardId": f"ics-binding-sync-{ctx.asset_slug}",
                    "card": {
                        "header": {
                            "title": title,
                            "subtitle": t(
                                "chat.subtitle",
                                loc,
                                visibility=t(f"chat.visibility.{ctx.link.visibility}", loc),
                            ),
                        },
                        "sections": [{"widgets": widgets}],
                    },
                }
            ]
        }
