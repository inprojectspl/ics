"""What `format=markdown` makes of a stored text file for an agent: HTML
converted to Markdown, Markdown without its HTML comments (machine markers
such as the timestamps of a meeting transcript are pure token noise)."""

from __future__ import annotations

import re
from collections.abc import Callable

from fastapi import status
from markdown_it import MarkdownIt
from markdown_it.token import Token

from app.collections_io import is_markdown_path
from app.errors import ApiError
from app.html_markdown import html_to_markdown

# A code span is matched only to be kept: `<!--` inside one is text.
_COMMENT_OR_CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`).*?(?<!`)\1(?!`)|<!--.*?-->", re.DOTALL)

_parser = MarkdownIt("commonmark")


def _is_comment(html: str) -> bool:
    return html.lstrip().startswith("<!--")


def _holds_comment(token: Token) -> bool:
    if token.type == "html_block":
        return _is_comment(token.content)
    return token.type == "inline" and any(
        child.type == "html_inline" and _is_comment(child.content) for child in token.children or ()
    )


def _drop_comment(match: re.Match[str]) -> str:
    # A multi-line comment leaves its line breaks, so no line moves.
    return match[0] if match[1] else "\n" * match[0].count("\n")


def strip_comments(text: str) -> str:
    """Remove the HTML comments (the de facto Markdown comment) that the
    parser reads as comments, so never one inside code. Every line keeps its
    number: line ranges and outline anchors of the stored file still apply."""
    lines = text.split("\n")
    for token in _parser.parse(text):
        if token.map and _holds_comment(token):
            start, end = token.map
            source = "\n".join(lines[start:end])
            lines[start:end] = _COMMENT_OR_CODE_SPAN.sub(_drop_comment, source).split("\n")
    return "\n".join(lines)


def markdown_converter(path: str) -> Callable[[str], str]:
    """The conversion `format=markdown` applies to the file at `path`."""
    if path.lower().endswith((".html", ".htm")):
        return html_to_markdown
    if is_markdown_path(path):
        return strip_comments
    raise ApiError(
        status.HTTP_400_BAD_REQUEST,
        "format_unsupported",
        "format=markdown works on .html and Markdown files only",
    )
