"""Structural outlines of asset content, cached in `Asset.outline_json` by the worker.

One schema per `kind` (md_single, md_collection, html_bundle, documents), part of
the MCP contract. Bundles get a file list only: their HTML is never parsed here.
Output over 512 KB keeps only level 1-2 headings and drops `wikilinks_out`.
"""

from __future__ import annotations

import mimetypes
import re
from collections.abc import Iterable

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_LINK_RE = re.compile(r"\[(?:[^\]]*)\]\(([^)]+)\)")
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]")

_MAX_OUTLINE_BYTES = 512 * 1024


def heading_anchor(text: str) -> str:
    """GitHub-style anchor slug (lowercased, spaces->hyphens, ASCII fallback)."""
    out = text.lower().strip()
    out = re.sub(r"[^\w\s-]", "", out, flags=re.UNICODE)
    out = re.sub(r"\s+", "-", out)
    return out[:80] or "section"


def _parse_md(content: str) -> tuple[dict, list[str]]:
    """Outline plus the wikilink targets, in a single pass over the lines."""
    headings: list[dict] = []
    seen_anchors: dict[str, int] = {}
    link_count = 0
    targets: list[str] = []
    lines = content.splitlines() or [""]
    in_fence = False
    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            text = m.group(2)
            base = heading_anchor(text)
            seen_anchors[base] = seen_anchors.get(base, 0) + 1
            anchor = base if seen_anchors[base] == 1 else f"{base}-{seen_anchors[base] - 1}"
            headings.append({"level": level, "text": text, "line": idx, "anchor": anchor})
        link_count += len(_LINK_RE.findall(line))
        targets.extend(_WIKILINK_RE.findall(line))
    outline = {
        "headings": headings,
        "line_count": len(lines),
        "link_count": link_count,
        "wikilink_count": len(targets),
    }
    return outline, targets


def parse_md_outline(content: str) -> dict:
    """Headings + counts for a single Markdown document."""
    outline, _ = _parse_md(content)
    return outline


def parse_collection_file(content: str) -> dict:
    """Per-file outline plus the list of wikilink *targets* (paths only)."""
    outline, targets = _parse_md(content)
    return {**outline, "wikilinks_out": targets}


def build_md_single(content: str, title: str | None) -> dict:
    inner = parse_md_outline(content)
    return {
        "kind": "md_single",
        "title": title,
        **inner,
        "truncated": False,
    }


def build_document(
    kind: str, markdown: str, title: str | None, *, extra: dict, truncated: bool
) -> dict:
    """Outline of a converted document: headings of the Markdown `file-mcp` serves
    (their `line` lets an agent jump there) plus the type's `extra` fields."""
    return {
        "kind": kind,
        "title": title,
        **extra,
        **parse_md_outline(markdown),
        "truncated": truncated,
    }


def build_md_collection(
    entry_path: str | None,
    files: Iterable[tuple[str, str]],
    title: str | None,
) -> dict:
    """`files` = iterable of (path, content_text)."""
    file_entries: list[dict] = []
    edges = 0
    nodes = 0
    for path, content in files:
        nodes += 1
        per = parse_collection_file(content)
        edges += len(per["wikilinks_out"])
        # heuristic title: first H1 or filename
        title_guess: str | None = None
        for h in per["headings"]:
            if h["level"] == 1:
                title_guess = h["text"]
                break
        file_entries.append(
            {
                "path": path,
                "title": title_guess or path.rsplit("/", 1)[-1].removesuffix(".md"),
                "line_count": per["line_count"],
                "link_count": per["link_count"],
                "wikilink_count": per["wikilink_count"],
                "headings": per["headings"],
                "wikilinks_out": per["wikilinks_out"],
            }
        )
    return {
        "kind": "md_collection",
        "title": title,
        "entry_path": entry_path,
        "files": file_entries,
        "graph_stats": {"nodes": nodes, "edges": edges},
        "truncated": False,
    }


def build_html_bundle(
    entry_path: str | None,
    files: Iterable[tuple[str, int]],
    title: str | None,
) -> dict:
    """`files` = iterable of (path, size_bytes)."""
    file_entries = [
        {
            "path": path,
            "size_bytes": size,
            "mime": mimetypes.guess_type(path)[0] or "application/octet-stream",
        }
        for path, size in files
    ]
    return {
        "kind": "html_bundle",
        "title": title,
        "entry_path": entry_path,
        "files": file_entries,
        "truncated": False,
    }


def _end_lines(headings: list[dict], line_count: int | None) -> list[dict]:
    """Each heading with `end_line`: the line before the next heading of the
    same or a higher level, or the last line of the file."""
    last = line_count or (headings[-1]["line"] if headings else 0)
    out = [dict(h) for h in headings]
    open_: list[dict] = []
    for h in out:
        while open_ and open_[-1]["level"] >= h["level"]:
            closed = open_.pop()
            closed["end_line"] = max(h["line"] - 1, closed["line"])
        open_.append(h)
    for h in open_:
        h["end_line"] = max(last, h["line"])
    return out


def with_end_lines(outline: dict) -> dict:
    """The stored outline with `end_line` on every heading, computed on read
    so outlines stored before the field existed carry it too."""
    out = dict(outline)
    if isinstance(out.get("headings"), list):
        out["headings"] = _end_lines(out["headings"], out.get("line_count"))
    if out.get("kind") == "md_collection" and isinstance(out.get("files"), list):
        out["files"] = [
            {**f, "headings": _end_lines(f["headings"], f.get("line_count"))}
            if isinstance(f.get("headings"), list)
            else f
            for f in out["files"]
        ]
    return out


def cap_outline(outline: dict) -> dict:
    """Enforce 512 KB cap on the stored JSON. If exceeded, keep only top-level
    structure (headings level 1-2 / files list without wikilinks_out)."""
    import orjson

    raw = orjson.dumps(outline)
    if len(raw) <= _MAX_OUTLINE_BYTES:
        return outline

    trimmed = dict(outline)
    trimmed["truncated"] = True
    if trimmed.get("kind") in ("md_single", "office_doc"):
        trimmed["headings"] = [h for h in trimmed.get("headings", []) if h["level"] <= 2]
    elif trimmed.get("kind") == "md_collection":
        files = trimmed.get("files", [])
        trimmed["files"] = [
            {
                "path": f["path"],
                "title": f["title"],
                "line_count": f["line_count"],
                "headings": [h for h in f.get("headings", []) if h["level"] == 1][:3],
            }
            for f in files
        ]
    elif trimmed.get("kind") == "pdf_doc":
        trimmed["bookmarks"] = [b for b in trimmed.get("bookmarks", []) if b["level"] <= 2]
    # html_bundle is already small; nothing to trim.
    return trimmed
