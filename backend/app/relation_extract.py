"""Find references to ICS documents in text (ADR-0016, section 4); pure module.

Forms: `/v/<slug>` and `/s/<token>` URLs on the base host, `ics://asset/<slug>`,
`[[ics:<slug>]]` (grammar shared with the renderer). Code is skipped, and versions
are ignored because an edge points at the document.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qs, unquote, urlsplit

RefKind = Literal["slug", "share_token"]

MAX_REFS = 500

# Viewer sub-routes that are not file paths inside the asset.
_VIEWER_SUBROUTES = frozenset({"diff", "agent"})

_SLUG = r"[A-Za-z0-9]+"
_URL_RE = re.compile(r"https?://[^\s<>\"'()\[\]`]+", re.IGNORECASE)
_ICS_URI_RE = re.compile(
    rf"ics://asset/(?P<slug>{_SLUG})"
    r"(?:@v\d+)?"
    r"(?:/file/(?P<path>[^\s#<>\"'()\[\]`]+))?"
    r"(?:#(?P<anchor>[^\s<>\"'()\[\]`]+))?",
)
# Same bracket rule as the renderer: the first `]]` closes, no brackets or
# newlines inside.
_WIKILINK_RE = re.compile(r"\[\[(?P<content>[^\[\]\n]+)\]\]")
# Target of a `[[...]]` link after the alias (`|...`) is split off.
_ICS_TARGET_RE = re.compile(rf"^ics:(?P<slug>{_SLUG})(?:/(?P<path>[^#]+?))?/?(?:#(?P<anchor>.+))?$")
_V_PATH_RE = re.compile(rf"^/v/(?P<slug>{_SLUG})(?:/(?P<rest>.*))?$")
_S_PATH_RE = re.compile(r"^/s/(?P<token>[A-Za-z0-9_-]+)/?$")
_FENCE_RE = re.compile(r"^ {0,3}(?P<fence>`{3,}|~{3,})")
_INLINE_CODE_RE = re.compile(r"(?<!`)(`+)(?!`).+?(?<!`)\1(?!`)", re.DOTALL)
_TRAILING_PUNCT = ".,;:!?*_~"


@dataclass(frozen=True)
class Ref:
    kind: RefKind
    value: str
    path: str | None = None
    anchor: str | None = None


def parse_ics_target(target: str) -> tuple[str, str | None, str | None] | None:
    """`(slug, path, anchor)` of an `ics:<slug>[/file][#anchor]` wikilink
    target (alias already removed, whitespace stripped), or None. The slug
    is lower-cased; path and anchor are returned as written."""
    m = _ICS_TARGET_RE.match(target)
    if m is None:
        return None
    return m.group("slug").lower(), m.group("path"), m.group("anchor")


def _strip_code(text: str) -> str:
    """Drop fenced code blocks and inline code spans."""
    kept: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        m = _FENCE_RE.match(line)
        if fence is None:
            if m:
                fence = m.group("fence")
                continue
            kept.append(line)
        elif m and m.group("fence")[0] == fence[0] and len(m.group("fence")) >= len(fence):
            if not line.strip().lstrip(fence[0]):
                fence = None
    return _INLINE_CODE_RE.sub(" ", "\n".join(kept))


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = unquote(value).strip().strip("/")
    return value or None


def _rstrip_punct(value: str | None) -> str | None:
    return value.rstrip(_TRAILING_PUNCT) if value else value


def _first(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None


def _from_url(raw: str, host: str) -> Ref | None:
    url = raw.rstrip(_TRAILING_PUNCT)
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.netloc.lower() != host:
        return None
    query = parse_qs(parts.query)
    q_path = _clean(_first(query, "p"))
    anchor = _clean(parts.fragment)

    if m := _V_PATH_RE.match(parts.path):
        rest = _clean(m.group("rest"))
        path = q_path
        if rest and rest not in _VIEWER_SUBROUTES:
            path = rest
        return Ref("slug", m.group("slug").lower(), path, anchor)
    if m := _S_PATH_RE.match(parts.path):
        return Ref("share_token", m.group("token"), q_path, anchor)
    return None


def extract_refs(text: str, base_url: str) -> list[Ref]:
    """References to ICS documents in `text`, deduplicated, in order of first
    appearance, capped at `MAX_REFS`."""
    host = urlsplit(base_url).netloc.lower()
    body = _strip_code(text)

    found: list[tuple[int, Ref]] = []
    if host:
        for m in _URL_RE.finditer(body):
            ref = _from_url(m.group(0), host)
            if ref is not None:
                found.append((m.start(), ref))
    for m in _ICS_URI_RE.finditer(body):
        ref = Ref(
            "slug",
            m.group("slug").lower(),
            _clean(_rstrip_punct(m.group("path"))),
            _clean(_rstrip_punct(m.group("anchor"))),
        )
        found.append((m.start(), ref))
    for m in _WIKILINK_RE.finditer(body):
        parsed = parse_ics_target(m.group("content").partition("|")[0].strip())
        if parsed is not None:
            slug, path, anchor = parsed
            found.append((m.start(), Ref("slug", slug, _clean(path), _clean(anchor))))

    found.sort(key=lambda item: item[0])
    result: list[Ref] = []
    seen: set[Ref] = set()
    for _, ref in found:
        if ref in seen:
            continue
        seen.add(ref)
        result.append(ref)
        if len(result) >= MAX_REFS:
            break
    return result
