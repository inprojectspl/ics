"""Tests for collection upload helpers and wikilinks plugin output."""

import pytest

from app.collections_io import normalize_collection_path, pick_entry
from app.domain_errors import DomainError
from app.errors import domain_status
from app.markdown import render_markdown

# ---------- path normalization ----------


def test_normalize_strips_leading_slash():
    assert normalize_collection_path("/foo/bar.md") == "foo/bar.md"


def test_normalize_collapses_backslash():
    assert normalize_collection_path("foo\\bar.md") == "foo/bar.md"


def test_normalize_rejects_traversal():

    with pytest.raises(DomainError) as exc:
        normalize_collection_path("../escape.md")
    assert domain_status(exc.value) == 400


def test_normalize_rejects_empty():

    with pytest.raises(DomainError):
        normalize_collection_path("")


# ---------- entry-file picker ----------


def test_pick_entry_prefers_root_readme():
    paths = ["Notes/x.md", "README.md", "Drafts/y.md"]
    assert pick_entry(paths) == "README.md"


def test_pick_entry_falls_back_to_index_md():
    paths = ["Notes/x.md", "index.md"]
    assert pick_entry(paths) == "index.md"


def test_pick_entry_prefers_shallow_readme():
    paths = ["a/b/c/README.md", "Notes/x.md", "README.md"]
    assert pick_entry(paths) == "README.md"


def test_pick_entry_default_first_alpha_when_no_readme():
    paths = ["z.md", "a.md", "m/n.md"]
    assert pick_entry(paths) == "a.md"


# ---------- wikilinks rendering ----------


def test_wikilink_simple():
    html = render_markdown("Hello [[Start]] world")
    assert '<a class="wikilink" data-target="Start">Start</a>' in html


def test_wikilink_with_alias():
    html = render_markdown("See [[Notes/start|Get started]] doc")
    assert 'data-target="Notes/start"' in html
    assert ">Get started</a>" in html


def test_wikilink_inside_list():
    html = render_markdown("- [[A]]\n- [[B|alias]]")
    assert html.count('class="wikilink"') == 2


def test_wikilink_does_not_match_single_brackets():
    html = render_markdown("[a](b) and [text]")
    assert "wikilink" not in html


def test_wikilink_empty_target_is_ignored():
    html = render_markdown("[[]] should stay literal")
    assert 'class="wikilink"' not in html
