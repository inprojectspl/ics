"""Copyable asset addresses: the `ics_share` URL parameter and the shared
`share_context.js` bootstrap injected into asset pages on their own origin.

The parameter names the share link a visit started from; it is never proof of
access (the link is checked again on entry). Contract and limits:
docs/copyable-addresses.md. The broker mirrors the URL rules and the
head injection in `microapp-runtime/src/broker/share-context.js`.
"""

from __future__ import annotations

import hashlib
import html
import re
from functools import cache
from pathlib import Path
from typing import Literal
from urllib.parse import unquote

from app.services.version_banner import ascii_html

SHARE_PARAM = "ics_share"
TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{16,128}")
MAX_TARGET_LEN = 2048

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "static" / "share_context.js"

TokenState = Literal["none", "one", "invalid"]


# ---------- URL rules ----------


def _param_name(part: str) -> str:
    return unquote(part.partition("=")[0].replace("+", " "))


def read_token(query: str) -> tuple[TokenState, str | None]:
    """The token of a raw query string; repeated or malformed is invalid."""
    found = [
        unquote(part.partition("=")[2].replace("+", " "))
        for part in query.split("&")
        if part and _param_name(part) == SHARE_PARAM
    ]
    if not found:
        return "none", None
    if len(found) > 1 or not TOKEN_RE.fullmatch(found[0]):
        return "invalid", None
    return "one", found[0]


def with_token(query: str, token: str | None) -> str:
    """`query` with exactly one `ics_share=token` at the end (none for None);
    the other parameters keep their text and order."""
    parts = [p for p in query.split("&") if p and _param_name(p) != SHARE_PARAM]
    if token:
        parts.append(f"{SHARE_PARAM}={token}")
    return "&".join(parts)


def _unsafe(text: str) -> bool:
    return "\\" in text or any(ord(c) < 0x20 or ord(c) == 0x7F for c in text)


def clean_target(to: str | None) -> str | None:
    """A page of the asset to return to after the entry, as `path?query`
    relative to the asset's root, without the token; None for anything that
    could leave that root (absolute or network paths, dot segments, empty
    segments, control characters, their encoded forms)."""
    if not to or len(to) > MAX_TARGET_LEN or "#" in to or _unsafe(to):
        return None
    path, _, query = to.partition("?")
    once = unquote(path)
    for form in (path, once, unquote(once)):
        segments = form.split("/")
        if (
            _unsafe(form)
            or form.startswith("/")
            or any(s in (".", "..") for s in segments)
            or "" in segments[:-1]
        ):
            return None
    query = with_token(query, None)
    return f"{path}?{query}" if query else path


def target_url(prefix: str, target: str, token: str | None) -> str:
    """`{prefix}/{target}` with the token in its query."""
    path, _, query = target.partition("?")
    query = with_token(query, token)
    return f"{prefix}/{path}" + (f"?{query}" if query else "")


# ---------- the script ----------


@cache
def script() -> tuple[bytes, str]:
    """Source of `share_context.js` and its ETag."""
    body = _SCRIPT_PATH.read_bytes()
    return body, f'"{script_version()}"'


@cache
def script_version() -> str:
    """Content hash for the script's address (`?v=`), so it can be cached for good."""
    return hashlib.sha256(_SCRIPT_PATH.read_bytes()).hexdigest()[:16]


def script_tag(src: str, **attrs: str | None) -> str:
    """The bootstrap element, ASCII only (the page may declare any charset).
    Keyword names become `data-*` attributes (`asset_id` -> `data-asset-id`)."""
    parts = [f'<script src="{ascii_html(src)}"']
    for name, value in attrs.items():
        if value is not None:
            parts.append(f' data-{name.replace("_", "-")}="{ascii_html(value)}"')
    return "".join(parts) + "></script>"


# ---------- head injection ----------

_BOM = b"\xef\xbb\xbf"
_TAG = re.compile(rb"<(/?)([A-Za-z][A-Za-z0-9-]*)")
_CHARSET = re.compile(rb"charset\s*=|http-equiv\s*=\s*[\"']?content-type", re.IGNORECASE)
_RAW_TEXT_CLOSE = {
    b"title": re.compile(rb"</title\s*>", re.IGNORECASE),
    b"style": re.compile(rb"</style\s*>", re.IGNORECASE),
}
_HEAD_VOID = {b"meta", b"link", b"base"}


_TAG_REST = re.compile(rb"""(?:[^"'>]|"[^"]*"|'[^']*')*>""")


def _tag_end(raw: bytes, k: int) -> int:
    """Index after the `>` closing a tag, quotes respected; -1 if none."""
    m = _TAG_REST.match(raw, k)
    return m.end() if m else -1


def head_insert_at(raw: bytes) -> int:
    """Where the bootstrap goes: right after the charset declaration when it
    comes first, else before the first script or other content, so it runs
    before the page's own code and never lands in a comment or script text."""
    i = len(_BOM) if raw.startswith(_BOM) else 0
    n = len(raw)
    while True:
        while i < n and raw[i] in b" \t\r\n\f":
            i += 1
        if i >= n or raw[i] != 0x3C:
            return i
        if raw.startswith(b"<!--", i):
            close = raw.find(b"-->", i + 4)
            if close < 0:
                return i
            i = close + 3
            continue
        if raw.startswith((b"<!", b"<?"), i):
            close = raw.find(b">", i)
            if close < 0:
                return i
            i = close + 1
            continue
        m = _TAG.match(raw, i)
        if m is None or m.group(1):
            return i
        name = m.group(2).lower()
        end = _tag_end(raw, m.end())
        if end < 0:
            return i
        if name in (b"html", b"head"):
            i = end
        elif name in _HEAD_VOID:
            if name == b"meta" and _CHARSET.search(raw, m.end(), end):
                return end
            i = end
        elif name in _RAW_TEXT_CLOSE:
            close_m = _RAW_TEXT_CLOSE[name].search(raw, end)
            if close_m is None:
                return i
            i = close_m.end()
        else:
            return i


def inject_head(raw: bytes, snippet: str) -> bytes:
    at = head_insert_at(raw)
    return raw[:at] + snippet.encode("ascii") + raw[at:]


def recovery_page(*, lang: str, title: str, message: str, script_html: str) -> bytes:
    """Entry page served instead of a protected document without a session:
    no content of the asset, only the bootstrap that resumes the visit."""
    esc = html.escape
    return (
        f'<!doctype html><html lang="{esc(lang)}"><head><meta charset="utf-8">'
        f'<meta name="referrer" content="no-referrer"><title>{esc(title)}</title>'
        f"{script_html}</head><body><p>{esc(message)}</p></body></html>"
    ).encode()
