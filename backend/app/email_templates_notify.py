"""Notification e-mail (ADR-0023): one message per batch or daily digest.

Split from `email_templates.py` for the size budget; reuses its frame, palette and
buttons so every ICS e-mail looks the same.
"""

from __future__ import annotations

import html as html_lib
from collections.abc import Sequence
from typing import Final

from app.email_templates import (
    _ACCENT,
    _ACCENT_SOFT,
    _CARD,
    _DANGER,
    _DANGER_SOFT,
    _FONT,
    _INK,
    _INK_MUTE,
    _INK_SOFT,
    _RULE,
    _SUBTLE,
    _SUCCESS,
    _SUCCESS_SOFT,
    _cta,
    _h1,
    _p,
    _shell,
    _signature,
)
from app.i18n import Locale, t, t_html, tn
from app.services.notifications.render import Rendered

# Glyph and tone per event; plain characters, since remote images are off.
_TONES: Final[dict[str, tuple[str, str]]] = {
    "accent": (_ACCENT, _ACCENT_SOFT),
    "success": (_SUCCESS, _SUCCESS_SOFT),
    "danger": (_DANGER, _DANGER_SOFT),
}
_BADGES: Final[dict[str, tuple[str, str]]] = {
    "asset.created": ("+", "accent"),
    "asset.added": ("↳", "accent"),
    "asset.updated": ("✎", "success"),
    "asset.deleted": ("✕", "danger"),
    "channel.chat_disabled": ("!", "danger"),
}


def _badge(code: str) -> str:
    glyph, tone = _BADGES.get(code, ("•", "accent"))
    ink, tint = _TONES[tone]
    return (
        f'<td width="44" valign="top" style="width:44px;padding:2px 12px 0 0;">'
        f'<div class="e-tone-{tone}" style="width:36px;height:36px;line-height:36px;border-radius:10px;'
        f"background:{tint};color:{ink};text-align:center;font-family:{_FONT};"
        f'font-size:17px;font-weight:700;">{glyph}</div></td>'
    )


def _meta(item: Rendered) -> str:
    """Actor, project chip and time; a notice without an actor shows its
    sentence instead, which must stay free to wrap."""
    parts = [html_lib.escape(item.actor)] if item.actor else []
    if item.project:
        parts.append(
            f'<span class="e-subtle e-soft" style="display:inline-block;padding:1px 8px;border-radius:999px;'
            f'background:{_SUBTLE};color:{_INK_SOFT};font-size:12px;">{html_lib.escape(item.project)}</span>'
        )
    if item.when:
        parts.append(html_lib.escape(item.when))
    # The separator sticks to the part before it, so a wrap never leaves it
    # alone at the start or end of a line.
    meta = " ".join(
        f'<span style="white-space:nowrap;">{part}{"&nbsp;·" if i < len(parts) - 1 else ""}</span>'
        for i, part in enumerate(parts)
    )
    if item.actor:
        return meta
    return html_lib.escape(item.body) + (f"<br>{meta}" if meta else "")


def _card(item: Rendered, locale: Locale) -> str:
    tone = _BADGES.get(item.code, ("", "accent"))[1]
    ink = _TONES[tone][0]
    title = html_lib.escape(item.subject)
    if item.url:
        title = (
            f'<a class="e-ink" href="{html_lib.escape(item.url)}" style="color:{_INK};text-decoration:none;">'
            f"{title}</a>"
        )
        button = (
            f'<a class="e-btn" href="{html_lib.escape(item.url)}" style="display:inline-block;margin-top:10px;'
            f"padding:6px 14px;border-radius:10px;border:1px solid {_RULE};background:{_CARD};"
            f"color:{_INK};text-decoration:none;font-family:{_FONT};font-size:13px;"
            f'font-weight:600;">{html_lib.escape(t("email.notify.open", locale))}</a>'
        )
    else:
        button = ""
    return (
        f'<tr><td class="e-rule" style="padding:16px 0;border-top:1px solid {_RULE};">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f"<tr>{_badge(item.code)}"
        f'<td valign="top" style="font-family:{_FONT};">'
        f'<div class="e-text-{tone}" style="font-size:12px;font-weight:600;'
        f'color:{ink};margin-bottom:2px;">'
        f"{html_lib.escape(item.label)}</div>"
        f'<div class="e-ink" style="font-size:16px;font-weight:600;'
        f'color:{_INK};line-height:1.4;">{title}</div>'
        f'<div class="e-mute" style="margin-top:4px;font-size:13px;'
        f'color:{_INK_MUTE};line-height:1.6;">{_meta(item)}</div>'
        f"{button}</td></tr></table></td></tr>"
    )


def notification_digest(
    *,
    items: Sequence[Rendered],
    inbox_url: str,
    settings_url: str,
    unsubscribe_url: str,
    daily: bool,
    locale: Locale,
) -> tuple[str, str, str]:
    """`(subject, text, html)`; `items` newest first, at least one."""
    n = len(items)
    first = items[0].title if items else ""
    if n == 1:
        subject = t("email.notify.subject.one", locale, first=first)
    else:
        subject = tn("email.notify.subject", n, locale, first=first)
    heading = (
        t("email.notify.digest_heading", locale) if daily else tn("email.notify.heading", n, locale)
    )

    text_rows = "\n\n".join(
        f"- {i.title}\n  {i.body}" + (f"\n  {i.url}" if i.url else "") for i in items
    )
    text = (
        f"{heading}\n\n{text_rows}\n\n"
        f"{t('email.notify.open_all', locale)}: {inbox_url}\n\n"
        f"{t('email.notify.why', locale)}\n"
        f"{t('email.notify.settings', locale)}: {settings_url}\n"
        f"{t('email.notify.unsubscribe', locale)}: {unsubscribe_url}\n\n"
        f"{_signature(locale)}"
    )

    link_style = f"color:{_INK_MUTE};text-decoration:underline;"
    footer = (
        f'<p class="e-mute" style="margin:20px 0 0;font-family:{_FONT};font-size:12px;'
        f'color:{_INK_MUTE};line-height:1.6;">{t_html("email.notify.why", locale)}<br>'
        f'<a class="e-mute" href="{html_lib.escape(settings_url)}" style="{link_style}">'
        f"{t_html('email.notify.settings', locale)}</a> &nbsp;·&nbsp; "
        f'<a class="e-mute" href="{html_lib.escape(unsubscribe_url)}" style="{link_style}">'
        f"{t_html('email.notify.unsubscribe', locale)}</a></p>"
    )
    body = (
        _h1(heading)
        + _p(t_html("email.notify.preheader", locale), mute=True)
        + '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        + "".join(_card(i, locale) for i in items)
        + "</table>"
        + f'<div class="e-rule" style="border-top:1px solid {_RULE};padding-top:8px;"></div>'
        + _cta(inbox_url, t("email.notify.open_all", locale))
        + footer
    )
    html = _shell(
        title=subject,
        preheader=t("email.notify.preheader", locale),
        content=body,
        locale=locale,
    )
    return subject, text, html
