"""Wikilink graph (`{nodes, edges}`) of an md_collection's current version.

Links resolve like the frontend renderer; broken ones are dropped (the text view
already marks them). Recomputed on demand, uncached.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

from app.collections_io import list_version_files, read_text_at_version
from app.config import Settings
from app.models import Asset

# Same shape as the markdown.py wikilinks_plugin: `[[target]]` or `[[target|alias]]`.
_WIKILINK_RE = re.compile(r"\[\[([^\[\]\n]+?)\]\]")

_TITLE_RE = re.compile(r"^\s*#\s+(.+)$", re.MULTILINE)


@dataclass
class GraphNode:
    path: str
    title: str
    out_degree: int = 0
    in_degree: int = 0


@dataclass
class GraphEdge:
    from_: str
    to: str


def _title_from(text: str, fallback_basename: str) -> str:
    """First `# heading` if present, else the filename without `.md`."""
    m = _TITLE_RE.search(text)
    if m:
        return m.group(1).strip()
    return fallback_basename.rsplit(".", 1)[0]


def _resolve(target: str, paths_set: frozenset[str], basenames: dict[str, str]) -> str | None:
    """Mirror of frontend resolveWikilink (lib/hydrateMarkdown.ts): exact path,
    then with `.md`, then by basename anywhere in the tree (Obsidian-style)."""
    t = target.strip()
    if not t:
        return None
    for cand in (t, f"{t}.md", t.lstrip("/") + ".md"):
        if cand in paths_set:
            return cand
    key = t.lower().removesuffix(".md")
    return basenames.get(key)


async def build_graph(asset: Asset, settings: Settings) -> dict:
    files = await list_version_files(asset, asset.version, settings)
    md_paths = [f for f in files if f.lower().endswith(".md")]
    paths_set = frozenset(md_paths)

    # On a shared basename the first sorted path wins, as in Obsidian.
    basenames: dict[str, str] = {}
    for p in md_paths:
        base = (p.split("/")[-1]).lower().removesuffix(".md")
        basenames.setdefault(base, p)

    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []
    seen_pairs: set[tuple[str, str]] = set()  # dedup parallel edges

    # Bounded parallelism: the S3 backend tolerates 8-16 concurrent GETs,
    # while a sequential loop over a 100-file collection costs 100 serial RTTs.
    sem = asyncio.Semaphore(8)

    async def _read(path: str) -> tuple[str, str | None]:
        async with sem:
            try:
                return path, await read_text_at_version(asset, asset.version, path, settings)
            except FileNotFoundError:
                return path, None

    fetched = await asyncio.gather(*(_read(p) for p in md_paths))

    for path, text in fetched:
        if text is None:
            continue
        nodes.setdefault(
            path, GraphNode(path=path, title=_title_from(text, path.rsplit("/", 1)[-1]))
        )
        for m in _WIKILINK_RE.finditer(text):
            raw = m.group(1)
            target = raw.split("|", 1)[0]
            resolved = _resolve(target, paths_set, basenames)
            if resolved is None or resolved == path:
                continue
            pair = (path, resolved)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            edges.append(GraphEdge(from_=path, to=resolved))
            nodes.setdefault(
                resolved,
                GraphNode(
                    path=resolved,
                    title=resolved.split("/")[-1].rsplit(".", 1)[0],
                ),
            )

    for e in edges:
        nodes[e.from_].out_degree += 1
        nodes[e.to].in_degree += 1

    return {
        "nodes": [
            {
                "path": n.path,
                "title": n.title,
                "out_degree": n.out_degree,
                "in_degree": n.in_degree,
            }
            for n in nodes.values()
        ],
        "edges": [{"from": e.from_, "to": e.to} for e in edges],
    }
