from app.markdown import render_markdown
from app.markdown_sanitize import sanitize


def test_basic_markdown_renders_to_html():
    out = render_markdown("# Hello\n\nworld")
    assert "<h1>Hello</h1>" in out
    assert "<p>world</p>" in out


def test_script_tag_is_not_rendered_as_html():
    """Raw HTML disabled at parser level -> script tag becomes escaped text, not real <script>."""
    out = render_markdown("# Title\n\n<script>alert(1)</script>\n\nrest")
    assert "<script>" not in out  # no executable script tag
    assert "&lt;script&gt;" in out  # escaped form is fine, won't execute


def test_javascript_protocol_link_not_rendered_as_link():
    """markdown-it refuses to build an <a href> for javascript: URLs; it stays as text."""
    out = render_markdown("[click](javascript:alert(1))")
    assert "<a " not in out  # critical: no anchor created
    assert "href=" not in out


def test_inline_html_is_escaped():
    """Raw HTML inputs should be HTML-escaped, not interpreted as DOM."""
    out = render_markdown("<img src=x onerror=alert(1)>")
    assert "<img" not in out  # no live img element
    assert "&lt;img" in out


def test_data_url_in_image_is_blocked():
    out = render_markdown("![x](data:text/html,<script>alert(1)</script>)")
    assert "<script>" not in out


def test_soft_break_becomes_br():
    """A single newline -> <br> (breaks=True), so the lines of a letter or
    offer do not merge into one paragraph."""
    out = render_markdown("**Addressee:** Board of Example Ltd.\n**Date:** 28 May 2026")
    assert "<br" in out
    # still one paragraph, but with a line break inside
    assert out.count("<p>") == 1


def test_table_renders():
    md = "| a | b |\n|---|---|\n| 1 | 2 |"
    out = render_markdown(md)
    assert "<table>" in out
    assert "<td>1</td>" in out


def test_strikethrough_renders():
    """GFM strikethrough: ~~text~~ -> <s>text</s>."""
    out = render_markdown("~~deleted~~")
    assert "<s>" in out or "<del>" in out


def test_task_list_renders_with_checkboxes():
    md = "- [x] done\n- [ ] todo"
    out = render_markdown(md)
    # The tasklist plugin emits input checkboxes.
    assert 'type="checkbox"' in out
    assert "done" in out
    assert "todo" in out


def test_footnote_renders():
    md = "Reference[^1].\n\n[^1]: footnote body"
    out = render_markdown(md)
    # A footnote emits a sup linking to the bottom section.
    assert "footnote" in out.lower() or "<sup" in out


def test_dollarmath_inline_renders_katex_block():
    """Inline `$x$` should be marked with the math class for KaTeX."""
    out = render_markdown("Hence $a^2 + b^2 = c^2$ holds.")
    # The dollarmath plugin marks it with math class markers.
    assert "math" in out.lower()


def test_dollarmath_display_renders_block():
    out = render_markdown("$$\\int_0^1 x dx$$")
    assert "math" in out.lower()


def test_dollar_amounts_are_not_parsed_as_math():
    """Amounts like `$650-750k` must not pair up into inline math, which
    would break the bold and glue half a sentence into KaTeX."""
    md = (
        "4. **A ~$0.7M credit line is a precondition, not an option.** "
        "However the negotiations go, the finance lead should have "
        # The en dash between amounts is what broke parsing, so it stays.
        "$650\u2013750k of liquidity secured before dropping to "
        "$350\u2013450k of headroom."
    )
    out = render_markdown(md)
    assert "math" not in out
    assert "<strong>" in out
    assert "**" not in out
    assert "$650" in out and "$350" in out


def test_definition_list_renders():
    md = "term\n: definition\n"
    out = render_markdown(md)
    # deflist plugin -> <dl><dt>term</dt><dd>definition</dd></dl>
    assert "<dt>" in out or "<dl>" in out


def test_obsidian_callout_renders_with_data_attr():
    """The custom callout plugin parses > [!note] title / > body."""
    md = "> [!note] My title\n> Body line"
    out = render_markdown(md)
    # Callout container with data-callout="note".
    assert 'data-callout="note"' in out or "callout" in out


def test_obsidian_callout_warning_type():
    md = "> [!warning] Caution\n> Body"
    out = render_markdown(md)
    assert "warning" in out


def test_wikilink_with_pipe_alias():
    """[[target|display]] syntax: display is rendered, target goes in a data attribute."""
    md = "See [[note|title]]."
    out = render_markdown(md)
    # The plugin may insert an <a> with data-wikilink or similar.
    assert "title" in out  # at least the display text


def test_wikilink_bare():
    md = "See [[note]]."
    out = render_markdown(md)
    assert "note" in out


def test_mark_plugin_renders_highlight():
    """`==text==` -> <mark>text</mark>."""
    out = render_markdown("plain ==highlighted== text")
    assert "<mark>" in out
    assert "highlighted" in out


def test_fenced_code_with_language():
    md = "```python\nprint('hi')\n```"
    out = render_markdown(md)
    # The Shiki highlighter (or the fallback) wraps the code in spans.
    assert "<pre" in out
    assert "print" in out


def test_mermaid_fenced_block_uses_data_attr():
    """```mermaid``` blocks must be marked so the frontend hydrator can
    replace them with SVG."""
    md = "```mermaid\ngraph TD; A-->B\n```"
    out = render_markdown(md)
    assert "mermaid" in out.lower()


def test_safe_link_renders_as_anchor():
    out = render_markdown("[link](https://example.com)")
    assert '<a href="https://example.com"' in out


def test_empty_input_returns_empty_output():
    assert render_markdown("") == ""


def test_paragraph_with_special_chars_escaped():
    out = render_markdown("Price: 5 < 10 & discount")
    # HTML entities are kept as text.
    assert "&lt;" in out or "<" not in out.replace("<p>", "").replace("</p>", "")
    assert "discount" in out


# ---------- data-* allowlist ----------
# Raw HTML is disabled in the parser, so these call the sanitizer directly:
# the allowlist is the second line of defence if that ever changes.


def test_raw_html_data_attributes_are_stripped():
    out = sanitize('<span data-foo="x" data-lucide="bomb" data-rendered="1">hi</span>')
    assert "data-foo" not in out
    assert "data-lucide" not in out
    assert "data-rendered" not in out
    assert "hi" in out


def test_renderer_markers_survive_only_with_valid_values():
    out = sanitize('<aside data-callout="evil">a</aside><pre data-widget="x">b</pre>')
    assert "data-callout" not in out
    assert "data-widget" not in out


def test_renderer_data_attributes_survive():
    src = (
        "> [!warning] Heads up\n>\n> body\n\n"
        "See [[Other Page]].\n\n"
        "```python\nprint(1)\n```\n\n"
        "```mermaid\ngraph TD; A-->B\n```\n"
    )
    out = render_markdown(src)
    assert 'data-callout="warning"' in out
    assert 'data-callout-icon="warning"' in out
    assert 'data-target="Other Page"' in out
    assert 'data-widget="code"' in out
    assert 'data-lang="python"' in out
    assert 'data-widget="mermaid"' in out
