"""Unit tests for `app.agent_markdown`: HTML comments leave the Markdown an
agent reads, comments in code stay, and no line changes its number."""

from __future__ import annotations

import pytest

from app.agent_markdown import markdown_converter, strip_comments
from app.errors import ApiError
from app.html_markdown import html_to_markdown

TRANSCRIPT = """# Meeting

<!-- generator v1 -->
- Date: Jan 5, 2026

<!-- t: 1700000000.25 0.5 -->
**[10:00:00] Anna:** Hi.
"""


def test_drops_comment_lines_and_keeps_line_numbers():
    out = strip_comments(TRANSCRIPT)
    assert "<!--" not in out
    assert out.split("\n") == [
        "# Meeting",
        "",
        "",
        "- Date: Jan 5, 2026",
        "",
        "",
        "**[10:00:00] Anna:** Hi.",
        "",
    ]


def test_multiline_comment_leaves_its_lines_empty():
    assert strip_comments("a\n\n<!--\nnote\n-->\nb") == "a\n\n\n\n\nb"


def test_inline_comment_in_a_paragraph_and_a_list():
    assert strip_comments("**x** <!-- y --> z\n- item <!-- l -->") == "**x**  z\n- item "


def test_comment_inside_code_stays():
    text = "```html\n<!-- fenced -->\n```\n\n    <!-- indented -->\n\nsee `<!-- span -->` <!-- gone -->"
    assert strip_comments(text) == (
        "```html\n<!-- fenced -->\n```\n\n    <!-- indented -->\n\nsee `<!-- span -->` "
    )


def test_text_without_comments_is_unchanged():
    text = "# T\n\nplain `code` and <b>html</b>\r\n"
    assert strip_comments(text) == text


def test_converter_by_path():
    assert markdown_converter("notes/a.MD") is strip_comments
    assert markdown_converter("b.markdown") is strip_comments
    assert markdown_converter("index.htm") is html_to_markdown
    with pytest.raises(ApiError) as exc:
        markdown_converter("app.css")
    assert exc.value.code == "format_unsupported"
