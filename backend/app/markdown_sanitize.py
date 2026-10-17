"""HTML allowlist sanitizer applied to rendered Markdown.

Kept apart from `app.markdown` for the file size budget; `app.render_cache`
hashes both modules, so any change here invalidates cached HTML.
"""

from __future__ import annotations

import re
from collections.abc import Callable

import bleach

from app.constants import CALLOUT_TYPES

ALLOWED_TAGS = {
    # Block
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "p",
    "div",
    "span",
    "br",
    "hr",
    "blockquote",
    "pre",
    "code",
    "ul",
    "ol",
    "li",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "dl",
    "dt",
    "dd",
    "figure",
    "figcaption",
    "details",
    "summary",
    "aside",
    # Inline
    "a",
    "strong",
    "em",
    "b",
    "i",
    "s",
    "del",
    "ins",
    "u",
    "sub",
    "sup",
    "small",
    "mark",
    "kbd",
    "samp",
    "var",
    "abbr",
    "cite",
    "q",
    "time",
    "data",
    # Media
    "img",
    "audio",
    "video",
    "source",
    "track",
    # KaTeX outputs <math> elements as <span class="katex"> structures with deeply nested
    # spans; span coverage handles them. Math semantic root we accept too:
    "math",
    "annotation",
    "semantics",
    "mrow",
    "mi",
    "mn",
    "mo",
    "ms",
    "mfrac",
    "msup",
    "msub",
    "msubsup",
    "mtext",
    "mspace",
    "mover",
    "munder",
    "munderover",
    "msqrt",
    "mroot",
    "mstyle",
    "merror",
    "mphantom",
    # Embed
    "iframe",
    # Input only for task-list checkboxes
    "input",
    # Footnotes uses <section>
    "section",
}

ALLOWED_ATTRS = {
    "*": ["class", "id", "aria-label", "aria-hidden", "role", "title", "lang", "dir"],
    "a": ["href", "rel", "target", "name"],
    "img": ["src", "alt", "width", "height", "loading", "decoding"],
    "audio": ["src", "controls", "preload"],
    "video": ["src", "controls", "preload", "poster", "width", "height"],
    "source": ["src", "type", "media"],
    "track": ["src", "kind", "srclang", "label", "default"],
    "iframe": [
        "src",
        "width",
        "height",
        "frameborder",
        "allow",
        "allowfullscreen",
        "loading",
        "sandbox",
        "referrerpolicy",
    ],
    "input": ["type", "checked", "disabled"],
    "th": ["scope", "colspan", "rowspan", "align"],
    "td": ["colspan", "rowspan", "align"],
    "ol": ["start", "reversed", "type"],
    "li": ["value"],
    "time": ["datetime"],
    "data": ["value"],
    "abbr": ["title"],
    "details": ["open"],
}

ALLOWED_PROTOCOLS = ["http", "https", "mailto", "tel"]

# Iframe src must be on the embed allowlist.
_IFRAME_HOST_ALLOWLIST = {
    "www.youtube.com",
    "youtube.com",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
    "player.vimeo.com",
}


def _iframe_src_allowed(value: str) -> bool:
    m = re.match(r"https?://([^/]+)", value, re.IGNORECASE)
    return bool(m and m.group(1).lower() in _IFRAME_HOST_ALLOWLIST)


_LANG = re.compile(r"[A-Za-z0-9_+#.-]{1,40}")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_ICS_SLUG = re.compile(r"[a-z0-9]{1,64}")


def _wikilink_target(value: str) -> bool:
    return 0 < len(value) <= 512 and not _CONTROL.search(value)


# Only the data-* attributes the renderer itself emits survive, and only on
# the tag it emits them on. Raw HTML in a note could otherwise forge the
# markers the frontend hydration keys on (data-rendered, data-lucide, ...).
_DATA_ATTRS: dict[tuple[str, str], Callable[[str], bool]] = {
    ("aside", "data-callout"): CALLOUT_TYPES.__contains__,
    ("span", "data-callout-icon"): CALLOUT_TYPES.__contains__,
    ("a", "data-target"): _wikilink_target,
    ("a", "data-ics-slug"): lambda v: _ICS_SLUG.fullmatch(v) is not None,
    ("pre", "data-widget"): lambda v: v in ("mermaid", "code"),
    ("pre", "data-lang"): lambda v: _LANG.fullmatch(v) is not None,
}


def _attr_check(tag: str, name: str, value: str) -> bool:
    """Bleach attribute callback; an iframe `src` must be on the embed host allowlist."""
    if name.startswith("data-"):
        check = _DATA_ATTRS.get((tag, name))
        return bool(check and check(value))
    if tag == "iframe" and name == "src":
        return _iframe_src_allowed(value)
    return name in _ALLOWED_ATTRS_BY_TAG.get(tag, _GLOBAL_ATTRS)


# Merged once: bleach calls `_attr_check` for every attribute of every element.
_GLOBAL_ATTRS: frozenset[str] = frozenset(ALLOWED_ATTRS.get("*", []))
_ALLOWED_ATTRS_BY_TAG: dict[str, frozenset[str]] = {
    tag: frozenset(attrs) | _GLOBAL_ATTRS for tag, attrs in ALLOWED_ATTRS.items() if tag != "*"
}


def sanitize(raw: str) -> str:
    return bleach.clean(
        raw,
        tags=ALLOWED_TAGS,
        attributes=_attr_check,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
    )
