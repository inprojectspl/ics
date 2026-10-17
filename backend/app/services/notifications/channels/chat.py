"""Personal Google Chat webhook: one Cards v2 message per batch."""

from __future__ import annotations

import html
from collections.abc import Sequence
from typing import Final, Literal

from app.i18n import t, tn

from .._providers.google_chat import GoogleChatProvider
from ..render import Rendered

_MAX_ROWS: Final[int] = 10
_ICONS: Final[dict[str, str]] = {
    "asset.created": "DESCRIPTION",
    "asset.added": "BOOKMARK",
    "asset.updated": "EDIT",
    "asset.deleted": "DELETE",
    "channel.chat_disabled": "NOTIFICATIONS_OFF",
}

ChatResult = Literal["ok", "disable", "retry"]


def build_card(items: Sequence[Rendered], locale: str | None) -> dict[str, object]:
    """`items` newest first."""
    widgets: list[dict[str, object]] = []
    for r in items[:_MAX_ROWS]:
        row: dict[str, object] = {
            "startIcon": {"materialIcon": {"name": _ICONS.get(r.code, "NOTIFICATIONS")}},
            "text": f"<b>{html.escape(r.title)}</b>",
            "bottomLabel": r.body[:200],
            "wrapText": True,
        }
        if r.url:
            row["button"] = {
                "text": t("chat.notify.open", locale),
                "onClick": {"openLink": {"url": r.url}},
            }
        widgets.append({"decoratedText": row})
    return {
        "cardsV2": [
            {
                "cardId": "ics-notifications",
                "card": {
                    "header": {
                        "title": t("chat.notify.title", locale),
                        "subtitle": tn("chat.notify.subtitle", len(items), locale),
                    },
                    "sections": [{"widgets": widgets}],
                },
            }
        ]
    }


def sample_card(locale: str | None) -> dict[str, object]:
    return {
        "cardsV2": [
            {
                "cardId": "ics-notifications-test",
                "card": {
                    "header": {
                        "title": t("chat.notify.title", locale),
                        "subtitle": t("chat.notify.test_title", locale),
                    },
                    "sections": [
                        {
                            "widgets": [
                                {"textParagraph": {"text": t("chat.notify.test_body", locale)}}
                            ]
                        }
                    ],
                },
            }
        ]
    }


def classify(status: int | None) -> ChatResult:
    """A deleted webhook or space answers 400/403/404: stop posting there.
    Rate limits, server errors and network failures are retried."""
    if status is not None and status < 400:
        return "ok"
    if status in (400, 401, 403, 404):
        return "disable"
    return "retry"


async def post(url: str, payload: dict[str, object]) -> ChatResult:
    return classify(await GoogleChatProvider().post(url, payload))
