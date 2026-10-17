"""Markdown rendering: markdown-it with plugins, then the bleach allowlist.

Output is semantic HTML plus data attributes; the frontend (hydrateMarkdown) styles
it by tag and mounts widgets (Mermaid, KaTeX, copy buttons) from the attributes.
"""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import quote

from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.deflist import deflist_plugin
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.tasklists import tasklists_plugin

from app.constants import CALLOUT_TYPES
from app.markdown_sanitize import sanitize
from app.relation_extract import parse_ics_target

# Custom plugins


_CALLOUT_RE = re.compile(r"^\[!(\w+)\]([+-]?)\s*(.*)$")


def callout_plugin(md: MarkdownIt) -> None:
    """Obsidian-style callouts (`> [!warning] Title`) as `<aside>` with a title row
    and a body."""

    def rule(state: Any) -> None:
        tokens = state.tokens
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok.type != "blockquote_open":
                i += 1
                continue

            j = i + 1
            inner_inline_idx = -1
            depth = 1
            while j < len(tokens) and depth > 0:
                t = tokens[j]
                if t.type == "blockquote_open":
                    depth += 1
                if t.type == "blockquote_close":
                    depth -= 1
                    if depth == 0:
                        break
                if t.type == "inline" and inner_inline_idx == -1 and depth == 1:
                    inner_inline_idx = j
                j += 1
            blockquote_close_idx = j

            if inner_inline_idx == -1:
                i = blockquote_close_idx + 1
                continue

            inline_tok = tokens[inner_inline_idx]
            first_line = inline_tok.content.split("\n", 1)[0]
            m = _CALLOUT_RE.match(first_line)
            if not m:
                i = blockquote_close_idx + 1
                continue

            ctype = m.group(1).lower()
            if ctype not in CALLOUT_TYPES:
                ctype = "note"
            title_text = m.group(3).strip() or ctype.capitalize()

            para_open_idx = inner_inline_idx - 1
            para_close_idx = inner_inline_idx + 1
            if (
                tokens[para_open_idx].type != "paragraph_open"
                or tokens[para_close_idx].type != "paragraph_close"
            ):
                i = blockquote_close_idx + 1
                continue

            # Only the title line is consumed. Body text on the same paragraph is
            # re-rendered on its own: mutating the inline token doubled content.
            remaining = inline_tok.content.split("\n", 1)
            inline_body_text = remaining[1].strip() if len(remaining) > 1 else ""

            callout_open = Token("callout_open", "aside", 1)
            callout_open.attrSet("class", f"callout callout-{ctype}")
            callout_open.attrSet("data-callout", ctype)

            title_open = Token("callout_title_open", "div", 1)
            title_text_tok = Token("callout_title_text", "", 0)
            title_text_tok.content = title_text
            title_text_tok.meta = {"callout_type": ctype}
            title_close = Token("callout_title_close", "div", -1)

            body_open = Token("callout_body_open", "div", 1)
            body_close = Token("callout_body_close", "div", -1)
            callout_close = Token("callout_close", "aside", -1)

            new_tokens: list[Token] = [
                callout_open,
                title_open,
                title_text_tok,
                title_close,
                body_open,
            ]

            if inline_body_text:
                html_tok = Token("html_block", "", 0)
                body_html = state.md.render(inline_body_text).strip()
                html_tok.content = body_html
                html_tok.block = True
                new_tokens.append(html_tok)

            after_title_tokens = tokens[para_close_idx + 1 : blockquote_close_idx]
            new_tokens.extend(after_title_tokens)

            new_tokens.append(body_close)
            new_tokens.append(callout_close)

            tokens[i : blockquote_close_idx + 1] = new_tokens
            i += len(new_tokens)

    md.core.ruler.after("block", "callout", rule)

    def render_callout_open(_self: Any, tokens: list[Token], idx: int, *_a: Any) -> str:
        attrs = tokens[idx].attrs or {}
        cls = attrs.get("class", "")
        ct = attrs.get("data-callout", "note")
        return f'<aside class="{cls}" data-callout="{ct}">'

    def render_callout_close(*_a: Any) -> str:
        return "</aside>"

    def render_title_open(*_a: Any) -> str:
        return '<div class="callout-title-row">'

    def render_title_text(_self: Any, tokens: list[Token], idx: int, *_a: Any) -> str:
        ct = tokens[idx].meta.get("callout_type", "note") if tokens[idx].meta else "note"
        title = html.escape(tokens[idx].content)
        return (
            f'<span class="callout-icon" data-callout-icon="{ct}" aria-hidden="true"></span>'
            f'<span class="callout-title">{title}</span>'
        )

    def render_title_close(*_a: Any) -> str:
        return "</div>"

    def render_body_open(*_a: Any) -> str:
        return '<div class="callout-body">'

    def render_body_close(*_a: Any) -> str:
        return "</div>"

    md.add_render_rule("callout_open", render_callout_open)
    md.add_render_rule("callout_close", render_callout_close)
    md.add_render_rule("callout_title_open", render_title_open)
    md.add_render_rule("callout_title_text", render_title_text)
    md.add_render_rule("callout_title_close", render_title_close)
    md.add_render_rule("callout_body_open", render_body_open)
    md.add_render_rule("callout_body_close", render_body_close)


def _ics_href(slug: str, path: str | None, anchor: str | None) -> str:
    """Viewer URL of another asset. The SPA addresses a file inside a
    collection with `?p=`, not with a path segment after the slug."""
    href = f"/v/{slug}"
    if path:
        href += "?p=" + quote(path.strip("/"), safe="/")
    if anchor:
        href += "#" + quote(anchor.strip(), safe="")
    return href


def wikilinks_plugin(md: MarkdownIt) -> None:
    """`[[Target|Alias]]` wikilinks and `[[ics:<slug>[/file][#anchor][|alias]]]` links.

    Wikilinks carry `data-target` for the frontend to resolve, keeping the renderer
    pure. Unaliased `ics:` links show the slug plus `data-ics-slug`: the title is
    per viewer, so it stays out of the cached HTML (ADR-0006).
    """

    def tokenize(state: Any, silent: bool) -> bool:
        if silent:
            return False
        src = state.src
        pos = state.pos
        if pos + 1 >= state.posMax or src[pos] != "[" or src[pos + 1] != "[":
            return False
        end = src.find("]]", pos + 2)
        if end == -1:
            return False
        content = src[pos + 2 : end]
        if not content or "\n" in content or "[" in content or "]" in content:
            return False
        if "|" in content:
            target, _, alias = content.partition("|")
            target = target.strip()
            alias = alias.strip()
        else:
            target = content.strip()
            alias = ""
        if not target:
            return False
        # `[[ics:<slug>[/file][#anchor]]]` points at another asset (ADR-0016).
        ics = parse_ics_target(target)
        if ics is not None:
            slug, path, anchor = ics
            tok = state.push("ics_link", "a", 0)
            tok.attrSet("href", _ics_href(slug, path, anchor))
            if not alias:
                # The client swaps the slug for the title the viewer may see.
                tok.attrSet("data-ics-slug", slug)
            tok.content = alias or (f"{slug}/{path}" if path else slug)
            state.pos = end + 2
            return True
        alias = alias or target
        tok = state.push("wikilink", "a", 0)
        tok.attrSet("class", "wikilink")
        tok.attrSet("data-target", target)
        tok.content = alias
        state.pos = end + 2
        return True

    def render_wikilink(_self: Any, tokens: list[Token], idx: int, *_a: Any) -> str:
        t = tokens[idx]
        attrs = t.attrs or {}
        target = html.escape(str(attrs.get("data-target", "")))
        return f'<a class="wikilink" data-target="{target}">{html.escape(t.content)}</a>'

    def render_ics_link(_self: Any, tokens: list[Token], idx: int, *_a: Any) -> str:
        t = tokens[idx]
        attrs = t.attrs or {}
        href = html.escape(str(attrs.get("href", "")))
        slug = attrs.get("data-ics-slug")
        data = f' data-ics-slug="{html.escape(str(slug))}"' if slug else ""
        return f'<a class="wikilink wikilink-ics" href="{href}"{data}>{html.escape(t.content)}</a>'

    md.inline.ruler.after("link", "wikilink", tokenize)
    md.add_render_rule("wikilink", render_wikilink)
    md.add_render_rule("ics_link", render_ics_link)


def mark_plugin(md: MarkdownIt) -> None:
    """`==highlighted==` -> <mark>highlighted</mark>."""

    def tokenize(state: Any, silent: bool) -> bool:
        if silent:
            return False
        src = state.src
        pos = state.pos
        if pos + 1 >= state.posMax or src[pos] != "=" or src[pos + 1] != "=":
            return False
        end = src.find("==", pos + 2)
        if end == -1 or end <= pos + 2:
            return False
        content = src[pos + 2 : end]
        if content.strip() == "" or "\n" in content:
            return False
        t_open = state.push("mark_open", "mark", 1)
        t_open.markup = "=="
        t_text = state.push("text", "", 0)
        t_text.content = content
        t_close = state.push("mark_close", "mark", -1)
        t_close.markup = "=="
        state.pos = end + 2
        return True

    md.inline.ruler.after("emphasis", "mark", tokenize)


# Markdown-it factory


def _highlight(content: str, lang_name: str, _attrs: str) -> str:
    """Mermaid passes through; other code stays unstyled for client-side Shiki."""
    if lang_name == "mermaid":
        escaped = html.escape(content.rstrip("\n"))
        return f'<pre class="mermaid" data-widget="mermaid">{escaped}</pre>'
    escaped = html.escape(content)
    lang_attr = f' data-lang="{html.escape(lang_name)}"' if lang_name else ""
    return (
        f'<pre class="code-block" data-widget="code"{lang_attr}>'
        f'<code class="language-{html.escape(lang_name)}">{escaped}</code></pre>'
    )


def _build_md() -> MarkdownIt:
    md = (
        MarkdownIt(
            "commonmark",
            {
                "html": False,
                "linkify": True,
                "typographer": True,
                # A single newline -> <br>, as in GitHub and Obsidian.
                "breaks": True,
                "highlight": _highlight,
            },
        )
        .enable("table")
        .enable("strikethrough")
        .use(footnote_plugin)
        .use(deflist_plugin)
        .use(tasklists_plugin, enabled=True, label=True)
        # Pandoc `$` rules, so amounts like "$650k ... $350k" do not pair up as math.
        .use(
            dollarmath_plugin,
            allow_labels=False,
            double_inline=True,
            allow_space=False,
            allow_digits=False,
        )
        .use(mark_plugin)
        .use(wikilinks_plugin)
        .use(callout_plugin)
    )
    return md


_md = _build_md()


def render_markdown(text: str) -> str:
    return sanitize(_md.render(text))


async def render_markdown_async(text: str) -> str:
    """Async wrapper: markdown-it + bleach take 30-150 ms of CPU for 10-50 KB of
    MD; running inline in an async route would block the event loop (DoS on
    public endpoints)."""
    import asyncio

    return await asyncio.to_thread(render_markdown, text)
