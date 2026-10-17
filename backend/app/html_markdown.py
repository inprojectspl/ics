"""HTML -> Markdown for token-efficient agent reads (e.g. `file-mcp` with
`format=markdown`), keeping tables, headings, lists and links structured."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup
from markdownify import MarkdownConverter

# No content for the reader, pure token noise: removed entirely.
_NOISE_TAGS = ("script", "style", "noscript", "template", "svg", "head", "iframe")

_BLANK_RUNS = re.compile(r"\n{3,}")


class _Converter(MarkdownConverter):
    """markdownify leaves `|` in table cells as is, which splits the cell
    and shifts every column after it."""

    def convert_td(self, el, text, parent_tags):
        return super().convert_td(el, text.replace("|", "\\|"), parent_tags)

    def convert_th(self, el, text, parent_tags):
        return super().convert_th(el, text.replace("|", "\\|"), parent_tags)


def html_to_markdown(html: str, *, infer_table_header: bool = False) -> str:
    """Convert HTML to Markdown, dropping non-content markup. Parse-only, so hostile
    HTML is inert. `infer_table_header` promotes the first row of a `<th>`-less
    table (converted Word/ODF) instead of emitting an empty header.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_NOISE_TAGS):
        tag.decompose()
    md = _Converter(
        heading_style="ATX", bullets="-", table_infer_header=infer_table_header
    ).convert_soup(soup)
    return _BLANK_RUNS.sub("\n\n", md).strip()
