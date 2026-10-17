"""Banners injected into served HTML bundles (archived version, superseded
document). Bundles run on an isolated origin without ICS chrome, so the warning
goes into the document itself: in normal flow, max `z-index`, inline
`!important` styles to beat the bundle's CSS, and ASCII only because the bundle
may declare any charset. Without inline script the close button just fails safe.
"""

from __future__ import annotations

import html
import re
from datetime import datetime

from app.i18n import Locale, t

_BODY_OPEN = re.compile(rb"<body\b[^>]*>", re.IGNORECASE)
#: Fallback for fragment documents without `<body>`.
_HEAD_CLOSE = re.compile(rb"</head\s*>", re.IGNORECASE)

_ID = "ics-version-banner"

_BAR_STYLE = (
    "position:relative!important;z-index:2147483647!important;"
    "display:block!important;visibility:visible!important;opacity:1!important;"
    "box-sizing:border-box!important;width:auto!important;max-width:none!important;"
    "margin:0!important;padding:10px 46px 10px 14px!important;"
    "border:0!important;border-bottom:1px solid #7a1710!important;"
    "background:#b42318!important;color:#ffffff!important;"
    "font:600 14px/1.45 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,"
    "Helvetica,Arial,sans-serif!important;text-align:left!important;"
    "letter-spacing:normal!important;text-transform:none!important;"
)

_CLOSE_STYLE = (
    "position:absolute!important;top:6px!important;right:8px!important;"
    "display:block!important;width:30px!important;height:30px!important;"
    "margin:0!important;padding:0!important;border:0!important;"
    "border-radius:4px!important;background:rgba(255,255,255,0.18)!important;"
    "color:#ffffff!important;font:700 18px/30px sans-serif!important;"
    "text-align:center!important;cursor:pointer!important;"
)


def _close_js(element_id: str) -> str:
    # Remove the node instead of `display:none`, so the page is not left with
    # a dead element its own selectors could match.
    return (
        f"var b=document.getElementById('{element_id}');"
        "if(b&&b.parentNode)b.parentNode.removeChild(b);return false;"
    )


_CLOSE_JS = _close_js(_ID)
_SUPERSEDED_ID = "ics-superseded-banner"
# Amber, not the archive red: the content is current for its version, but a
# newer document replaces it.
_SUPERSEDED_STYLE = _BAR_STYLE.replace("#b42318", "#93370d").replace("#7a1710", "#6b2a0a")
_LINK_STYLE = (
    "color:#ffffff!important;text-decoration:underline!important;"
    "font:inherit!important;margin-left:6px!important;"
)


def _ascii_html(text: str) -> str:
    """HTML escape plus every non-ASCII character as a numeric entity."""
    return html.escape(text).encode("ascii", "xmlcharrefreplace").decode("ascii")


def _fmt_dt(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%d %H:%M")


def build_banner_html(
    *,
    preview_version: int,
    current_version: int,
    preview_created_at: datetime | None = None,
    current_updated_at: datetime | None = None,
    locale: Locale,
) -> str:
    """Banner snippet for a preview of version `preview_version`."""
    preview_when = _fmt_dt(preview_created_at)
    current_when = _fmt_dt(current_updated_at)
    if preview_when:
        head = t("banner.preview_dated", locale, version=preview_version, date=preview_when)
    else:
        head = t("banner.preview", locale, version=preview_version)
    if current_when:
        tail = t("banner.current_dated", locale, version=current_version, date=current_when)
    else:
        tail = t("banner.current", locale, version=current_version)
    body = _ascii_html(f"{head}. {tail}.")
    close = _ascii_html(t("banner.close", locale))
    return (
        f'<div id="{_ID}" role="alert" style="{_BAR_STYLE}">{body}'
        f'<button type="button" aria-label="{close}" '
        f'onclick="{_CLOSE_JS}" style="{_CLOSE_STYLE}">&#215;</button>'
        f"</div>"
    )


def inject_banner(raw: bytes, snippet: str) -> bytes:
    """Insert `snippet` after `<body ...>`, else after `</head>`, else at the
    start. Works on bytes so non-UTF-8 pages are not re-encoded.
    """
    payload = snippet.encode("ascii")
    m = _BODY_OPEN.search(raw)
    if m is None:
        m = _HEAD_CLOSE.search(raw)
    if m is None:
        return payload + raw
    return raw[: m.end()] + payload + raw[m.end() :]


def build_superseded_banner_html(
    *,
    title: str | None,
    since: datetime | None,
    url: str,
    locale: Locale,
) -> str:
    """Banner for a bundle that a newer document supersedes. `url` opens the
    successor on the main ICS origin; the caller has checked that this
    visitor may open it."""
    name = title or t("banner.superseded_untitled", locale)
    when = since.strftime("%Y-%m-%d") if since else None
    head = (
        t("banner.superseded_dated", locale, title=name, date=when)
        if when
        else t("banner.superseded", locale, title=name)
    )
    body = _ascii_html(f"{head}.")
    link = _ascii_html(t("banner.superseded_open", locale))
    close = _ascii_html(t("banner.close", locale))
    href = _ascii_html(url)
    return (
        f'<div id="{_SUPERSEDED_ID}" role="alert" style="{_SUPERSEDED_STYLE}">{body}'
        f'<a href="{href}" target="_top" rel="noopener" style="{_LINK_STYLE}">{link}</a>'
        f'<button type="button" aria-label="{close}" '
        f'onclick="{_close_js(_SUPERSEDED_ID)}" style="{_CLOSE_STYLE}">&#215;</button>'
        f"</div>"
    )
