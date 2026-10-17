"""Text of an entry in the recipient's language, for e-mail, Chat and push."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.config import Settings
from app.i18n import t, tn
from app.services.sharing import build_app_url

from .items import entry_time, link_of


@dataclass(frozen=True, slots=True)
class Rendered:
    title: str
    body: str
    url: str | None
    tag: str
    code: str = ""
    # For the e-mail card: event label ("4 new versions · v6 → v9"), the
    # document title and who did it.
    label: str = ""
    subject: str = ""
    actor: str = ""
    project: str = ""
    # Local time of the event ("14:32", or "27.09 14:32" before today).
    when: str = ""


def _when(entry_id: str, settings: Settings) -> str:
    tz = ZoneInfo(settings.notifications_timezone)
    at = entry_time(entry_id).astimezone(tz)
    if at.date() == datetime.now(tz).date():
        return at.strftime("%H:%M")
    return at.strftime("%d.%m %H:%M")


def _actor(payload: dict[str, Any], locale: str | None) -> str:
    return payload.get("an") or t("notify.actor.system", locale)


def render(
    entry_id: str, payload: dict[str, Any], locale: str | None, settings: Settings
) -> Rendered:
    code = payload.get("c") or ""
    title = payload.get("t") or payload.get("sl") or ""
    params = {
        "title": title,
        "project": payload.get("pn") or "",
        "actor": _actor(payload, locale),
        "version": payload.get("v") or "",
    }
    count = int(payload.get("n") or 1)
    if code == "asset.updated":
        head = tn("notify.asset.updated.title", count, locale, **params)
    else:
        head = t(f"notify.{code}.title", locale, **params)
    several = int(payload.get("na") or 1) > 1
    body = t(f"notify.{code}.body{'_several' if several else ''}", locale, **params)
    if code == "asset.updated":
        label = tn("notify.label.asset.updated", count, locale)
        first, last = payload.get("fv"), payload.get("v")
        if isinstance(first, int) and isinstance(last, int) and first < last:
            label += f" · v{first} → v{last}"
        elif isinstance(last, int):
            label += f" · v{last}"
    else:
        label = t(f"notify.label.{code}", locale)
    link = link_of(payload)
    url = build_app_url(settings, link) if link else None
    tag = f"{code}:{payload.get('as') or entry_id}"
    return Rendered(
        title=head,
        body=body,
        url=url,
        tag=tag,
        code=code,
        label=label,
        subject=title or head,
        actor=params["actor"] if code != "channel.chat_disabled" else "",
        project=payload.get("pn") or "",
        when=_when(entry_id, settings) if "-" in entry_id else "",
    )
