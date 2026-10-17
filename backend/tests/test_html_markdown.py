"""Unit tests for `app.html_markdown.html_to_markdown`: non-obvious HTML
constructs must get a sensible Markdown representation, and noise (scripts,
styles, comments) must disappear entirely."""

from __future__ import annotations

from app.html_markdown import html_to_markdown


def test_headings_and_paragraphs():
    md = html_to_markdown("<h1>Title</h1><h3>Section</h3><p>Paragraph.</p>")
    assert "# Title" in md
    assert "### Section" in md
    assert "Paragraph." in md


def test_table_with_thead_tbody():
    md = html_to_markdown(
        "<table><thead><tr><th>Name</th><th>Age</th></tr></thead>"
        "<tbody><tr><td>Alice</td><td>30</td></tr>"
        "<tr><td>Bob</td><td>25</td></tr></tbody></table>"
    )
    assert "| Name | Age |" in md
    assert "| Alice | 30 |" in md
    assert "| Bob | 25 |" in md
    assert "---" in md  # table header separator


def test_nested_lists_keep_structure():
    md = html_to_markdown("<ul><li>a<ul><li>a1</li><li>a2</li></ul></li><li>b</li></ul>")
    assert "- a" in md
    assert "- a1" in md and "- a2" in md
    assert "- b" in md
    # nesting = indentation relative to the parent
    assert md.index("- a1") > md.index("- a")
    a1_line = next(line for line in md.splitlines() if "a1" in line)
    assert a1_line.startswith(("\t", "  ", "    "))


def test_ordered_list():
    md = html_to_markdown("<ol><li>one</li><li>two</li></ol>")
    assert "1. one" in md
    assert "2. two" in md


def test_links_and_images():
    md = html_to_markdown(
        '<p><a href="https://example.com">link text</a><img src="logo.png" alt="Company logo"></p>'
    )
    assert "[link text](https://example.com)" in md
    assert "![Company logo](logo.png)" in md


def test_pre_code_block_preserved():
    md = html_to_markdown("<pre><code>def f(x):\n    return x  # <important>\n</code></pre>")
    assert "def f(x):" in md
    assert "return x" in md
    # code gets a block representation (fence or indent), not a run of inline text
    assert "```" in md or "    def f(x):" in md


def test_inline_formatting():
    md = html_to_markdown("<p><strong>bold</strong> and <em>italic</em> plus <code>code</code></p>")
    assert "**bold**" in md
    assert "*italic*" in md
    assert "`code`" in md


def test_blockquote():
    md = html_to_markdown("<blockquote>quoted text</blockquote>")
    assert "> quoted text" in md


def test_html_comments_do_not_leak():
    md = html_to_markdown("<p>before</p><!-- secret: do not show -->\n<p>after</p>")
    assert "secret" not in md
    assert "before" in md and "after" in md


def test_script_style_head_noscript_stripped():
    md = html_to_markdown(
        "<html><head><title>head-title</title><style>.x{color:red}</style></head>"
        "<body><noscript>enable JS</noscript><script>var s='script-body'</script>"
        "<template><p>template-body</p></template><p>content</p></body></html>"
    )
    assert md.count("content") == 1
    for noise in ("head-title", "color:red", "script-body", "enable JS", "template-body"):
        assert noise not in md


def test_entities_decoded():
    md = html_to_markdown("<p>A&amp;B &lt;tag&gt; &copy; coffee&nbsp;with milk</p>")
    assert "A&B" in md
    assert "©" in md
    assert "coffee" in md and "milk" in md
    assert "&amp;" not in md and "&nbsp;" not in md


def test_malformed_html_does_not_crash():
    md = html_to_markdown("<div><p>unclosed <b>bold<p>next paragraph</div><span>")
    assert "unclosed" in md
    assert "next paragraph" in md


def test_br_becomes_line_break():
    md = html_to_markdown("<p>line one<br>line two</p>")
    one = next(line for line in md.splitlines() if "line one" in line)
    assert "line two" not in one


def test_definition_list_content_survives():
    md = html_to_markdown("<dl><dt>Term</dt><dd>Term definition</dd></dl>")
    assert "Term" in md
    assert "Term definition" in md


def test_blank_line_runs_collapsed():
    md = html_to_markdown("<p>a</p><div></div><div></div><div></div><p>b</p>")
    assert "\n\n\n" not in md


def test_full_page_shape():
    md = html_to_markdown(
        "<html><head><script src='app.js'></script></head><body>"
        "<nav><a href='/'>Home</a></nav>"
        "<h1>Report</h1><p>Report introduction.</p>"
        "<table><tr><th>K</th></tr><tr><td>v</td></tr></table>"
        "</body></html>"
    )
    assert md.startswith("[Home](/)") or md.startswith("# Report") or "# Report" in md
    assert "Report introduction." in md
    assert "| K |" in md
