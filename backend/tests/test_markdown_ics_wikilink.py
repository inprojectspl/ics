"""`[[ics:...]]` wikilinks between assets (ADR-0016, section 4)."""

from __future__ import annotations

import pytest

from app.markdown import _md, render_markdown
from app.markdown_sanitize import sanitize


@pytest.mark.parametrize(
    ("source", "href", "text", "slug"),
    [
        ("[[ics:abc234]]", "/v/abc234", "abc234", "abc234"),
        ("[[ics:ABC234]]", "/v/abc234", "abc234", "abc234"),
        ("[[ics:abc234/spec.md]]", "/v/abc234?p=spec.md", "abc234/spec.md", "abc234"),
        (
            "[[ics:abc234/dir/a b.md]]",
            "/v/abc234?p=dir/a%20b.md",
            "abc234/dir/a b.md",
            "abc234",
        ),
        ("[[ics:abc234#goals]]", "/v/abc234#goals", "abc234", "abc234"),
        (
            "[[ics:abc234/spec.md#scope-and-goals]]",
            "/v/abc234?p=spec.md#scope-and-goals",
            "abc234/spec.md",
            "abc234",
        ),
        # An alias is the author's text: the client leaves it alone.
        ("[[ics:abc234|The design]]", "/v/abc234", "The design", None),
        (
            "[[ics:abc234/spec.md#scope|Scope <b>]]",
            "/v/abc234?p=spec.md#scope",
            "Scope &lt;b&gt;",
            None,
        ),
    ],
)
def test_ics_wikilink_renders_as_link(source, href, text, slug):
    out = render_markdown(f"See {source} here.")
    data = f' data-ics-slug="{slug}"' if slug else ""
    assert f'<a class="wikilink wikilink-ics" href="{href}"{data}>{text}</a>' in out
    assert "data-target" not in out


def test_sanitizer_drops_forged_ics_slug():
    out = sanitize('<a href="/v/x" data-ics-slug="a b">x</a>')
    assert "data-ics-slug" not in out


def test_collection_wikilink_unchanged():
    out = render_markdown("[[notes/other.md|Other]] and [[plain]]")
    assert '<a class="wikilink" data-target="notes/other.md">Other</a>' in out
    assert '<a class="wikilink" data-target="plain">plain</a>' in out
    assert "href" not in out


def test_malformed_ics_target_falls_back_to_collection_wikilink():
    out = render_markdown("[[ics:not a slug]]")
    assert 'data-target="ics:not a slug"' in out
    assert "href" not in out


def test_sanitizer_keeps_href():
    raw = _md.render("[[ics:abc234/spec.md#scope|Spec]]")
    assert sanitize(raw) == raw
    assert 'href="/v/abc234?p=spec.md#scope"' in sanitize(raw)


def test_ics_wikilink_in_code_is_literal():
    out = render_markdown("`[[ics:abc234]]`")
    assert "<a" not in out
