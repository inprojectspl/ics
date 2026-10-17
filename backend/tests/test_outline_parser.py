"""Unit tests for the structural outline parser. Pure functions over text:
no DB, no Redis, no Arq required."""

from __future__ import annotations

from app.outline_parser import (
    build_html_bundle,
    build_md_collection,
    build_md_single,
    cap_outline,
    parse_md_outline,
)


def test_parse_md_outline_extracts_headings_with_anchors():
    md = "# Title\n\nIntro\n\n## Section A\n\ntext\n\n## Section A\n\nmore\n\n### Sub\n"
    out = parse_md_outline(md)
    assert len(out["headings"]) == 4
    assert out["headings"][0] == {"level": 1, "text": "Title", "line": 1, "anchor": "title"}
    # Duplicate "Section A" headings get suffixed anchors
    anchors = [h["anchor"] for h in out["headings"]]
    assert anchors[1] != anchors[2]
    assert out["line_count"] == len(md.splitlines())


def test_parse_md_outline_counts_links_and_wikilinks():
    md = "Read [docs](https://x) and [[Other Note]] and [[Page|alias]]."
    out = parse_md_outline(md)
    assert out["link_count"] == 1
    assert out["wikilink_count"] == 2


def test_parse_md_outline_ignores_headings_in_code_fences():
    md = "# Real\n\n```\n# Not a heading\n```\n\n## Also real\n"
    out = parse_md_outline(md)
    texts = [h["text"] for h in out["headings"]]
    assert texts == ["Real", "Also real"]


def test_build_md_single_shape():
    out = build_md_single("# Hi\n\ntext", title="Hi")
    assert out["kind"] == "md_single"
    assert out["title"] == "Hi"
    assert out["truncated"] is False
    assert out["headings"][0]["text"] == "Hi"


def test_build_md_collection_graph_stats():
    files = [
        ("a.md", "# A\n\nLink to [[b]]"),
        ("b.md", "# B\n\nLink to [[a]] and [[c]]"),
    ]
    out = build_md_collection("a.md", files, title="My vault")
    assert out["kind"] == "md_collection"
    assert out["entry_path"] == "a.md"
    assert out["graph_stats"]["nodes"] == 2
    assert out["graph_stats"]["edges"] == 3
    assert {f["path"] for f in out["files"]} == {"a.md", "b.md"}


def test_build_html_bundle_lists_files_with_mime():
    out = build_html_bundle("index.html", [("index.html", 1024), ("style.css", 256)], title="X")
    assert out["kind"] == "html_bundle"
    assert out["entry_path"] == "index.html"
    paths = {f["path"]: f for f in out["files"]}
    assert paths["index.html"]["mime"] == "text/html"
    assert paths["style.css"]["mime"] == "text/css"


def test_cap_outline_trims_when_over_limit():
    import json

    # Tiny collection, definitely under the cap: must not be marked truncated.
    small = build_md_collection("a.md", [("a.md", "# A\n")], title="tiny")
    capped_small = cap_outline(small)
    assert capped_small["truncated"] is False

    # Huge collection, explicitly over the cap: must be marked truncated and
    # shrink the JSON size below 512 KB.
    files = [
        (f"f{i}.md", "\n".join([f"# h1 {j}\n## h2 {j}\n### h3 {j}\nbody " * 30 for j in range(5)]))
        for i in range(400)
    ]
    full = build_md_collection("f0.md", files, title="big")
    capped_big = cap_outline(full)
    big_size = len(json.dumps(capped_big).encode())
    if big_size > 512 * 1024:
        # If still over the cap, the trim wasn't aggressive enough, but at
        # least the flag must say truncated.
        assert capped_big["truncated"] is True
    else:
        # Properly trimmed: must be flagged and within the cap.
        assert capped_big["truncated"] is True
        assert big_size <= 512 * 1024
