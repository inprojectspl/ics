"""Check that a relation's `target_path` and `target_anchor` exist in the
target's current version (ADR-0016). An anchor matches as given, then
case-insensitively, then as heading text. A refusal lists up to `MAX_CHOICES`
valid anchors or paths, so an agent can retry without reading the outline.
"""

from __future__ import annotations

import asyncio
import re

from app.collections_io import (
    decode_text,
    list_version_files,
    normalize_collection_path,
    read_bytes_at_version,
)
from app.config import Settings
from app.domain_errors import InvalidInputError
from app.models import Asset
from app.outline_parser import heading_anchor, parse_md_outline
from app.services import documents

_HTML_ID_RE = re.compile(r"""\b(?:id|name)\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_HTML_EXTENSIONS = (".html", ".htm")
MAX_CHOICES = 30


def _choices(key: str, values: list[str]) -> dict[str, object]:
    extra: dict[str, object] = {key: values[:MAX_CHOICES]}
    if len(values) > MAX_CHOICES:
        extra[f"{key}_total"] = len(values)
    return extra


def _path_not_found(paths: list[str]) -> InvalidInputError:
    return InvalidInputError(
        "relation_target_path_not_found",
        "target_path does not exist in the target's version",
        extra=_choices("paths", paths),
    )


def _anchors(text: str, *, html: bool) -> list[str]:
    """Anchors in document order, without duplicates."""
    found = (
        _HTML_ID_RE.findall(text)
        if html
        else [h["anchor"] for h in parse_md_outline(text)["headings"]]
    )
    return list(dict.fromkeys(found))


async def _target_text(asset: Asset, path: str | None, settings: Settings) -> tuple[str, bool]:
    """Text of the file the edge points into and whether it is HTML."""
    if documents.is_document(asset.kind):
        if path is not None and path != asset.entry_path:
            raise _path_not_found([asset.entry_path] if asset.entry_path else [])
        return await documents.markdown(asset, asset.version, settings), False
    entry = asset.entry_path or ("index.md" if asset.kind == "md_single" else None)
    if asset.kind == "md_single" and path is not None and path != entry:
        raise _path_not_found([entry] if entry else [])
    rel = path or entry
    if rel is None:
        raise _path_not_found(await list_version_files(asset, asset.version, settings))
    try:
        raw = await read_bytes_at_version(
            asset, asset.version, normalize_collection_path(rel), settings
        )
    except FileNotFoundError:
        raise _path_not_found(await list_version_files(asset, asset.version, settings)) from None
    html = rel.lower().endswith(_HTML_EXTENSIONS)
    text = decode_text(raw) if html else raw.decode("utf-8", errors="replace")
    return text or "", html


async def check_target_location(
    target: Asset, target_path: str | None, target_anchor: str | None, settings: Settings
) -> str | None:
    """Raise `relation_target_path_not_found` / `relation_target_anchor_not_found`
    when the location is missing; return the anchor to store."""
    if target_path is None and not target_anchor:
        return target_anchor
    text, html = await _target_text(target, target_path, settings)
    if not target_anchor:
        return target_anchor
    anchors = await asyncio.to_thread(_anchors, text, html=html)
    wanted = target_anchor.removeprefix("#")
    for candidate in (wanted, wanted.lower(), heading_anchor(wanted)):
        if candidate in anchors:
            return candidate
    raise InvalidInputError(
        "relation_target_anchor_not_found",
        "target_anchor matches no heading in the target's current version",
        extra=_choices("anchors", anchors),
    )
