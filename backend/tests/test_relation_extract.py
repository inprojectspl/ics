"""Reference extraction from document text (ADR-0016, section 4)."""

from __future__ import annotations

import ast
import inspect
import re

import pytest

from app import relation_extract
from app.markdown import render_markdown
from app.relation_extract import MAX_REFS, Ref, extract_refs

BASE = "https://ics.example.com"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("see https://ics.example.com/v/abc234", Ref("slug", "abc234")),
        (
            "[x](https://ics.example.com/v/abc234/docs/spec.md#scope)",
            Ref("slug", "abc234", "docs/spec.md", "scope"),
        ),
        (
            "<https://ics.example.com/v/abc234?p=a%20b.md&ver=3#h>",
            Ref("slug", "abc234", "a b.md", "h"),
        ),
        ("https://ics.example.com/v/abc234/diff?from=1&to=2", Ref("slug", "abc234")),
        ("https://ics.example.com/s/Tok_en-12", Ref("share_token", "Tok_en-12")),
        (
            "https://ics.example.com/s/Tok_en-12?p=x.md#intro.",
            Ref("share_token", "Tok_en-12", "x.md", "intro"),
        ),
        ("ics://asset/abc234", Ref("slug", "abc234")),
        ("ics://asset/abc234@v7", Ref("slug", "abc234")),
        (
            "ics://asset/abc234@v2/file/dir/a.md#goals.",
            Ref("slug", "abc234", "dir/a.md", "goals"),
        ),
        ("[[ics:abc234]]", Ref("slug", "abc234")),
        ("[[ics:abc234/file.md]]", Ref("slug", "abc234", "file.md")),
        ("[[ics:abc234#heading]]", Ref("slug", "abc234", anchor="heading")),
        (
            "[[ics:abc234/dir/file.md#heading|Alias text]]",
            Ref("slug", "abc234", "dir/file.md", "heading"),
        ),
        ("[[ics:ABC234|alias]]", Ref("slug", "abc234")),
    ],
)
def test_recognised_syntax(text, expected):
    assert extract_refs(text, BASE) == [expected]


def test_order_of_appearance_across_syntaxes():
    text = "[[ics:bbb]] then ics://asset/aaa then https://ics.example.com/v/ccc"
    assert [r.value for r in extract_refs(text, BASE)] == ["bbb", "aaa", "ccc"]


def test_fenced_code_block_ignored():
    text = (
        "before [[ics:keep]]\n"
        "````md\n"
        "[[ics:hidden1]] https://ics.example.com/v/hidden2\n"
        "```\n"
        "still code, a shorter fence does not close ics://asset/hidden3\n"
        "````\n"
        "~~~\n"
        "[[ics:hidden4]]\n"
        "~~~\n"
        "after ics://asset/tail\n"
    )
    assert [r.value for r in extract_refs(text, BASE)] == ["keep", "tail"]


def test_unclosed_fence_hides_rest():
    assert extract_refs("```\n[[ics:abc]]\n", BASE) == []


def test_inline_code_ignored():
    text = "use `[[ics:hidden]]` or ``ics://asset/also`` but [[ics:shown]]"
    assert extract_refs(text, BASE) == [Ref("slug", "shown")]


@pytest.mark.parametrize(
    "text",
    [
        "https://evil.example.com/v/abc234",
        "https://ics.example.com.evil.net/v/abc234",
        "https://ics.example.com:8443/v/abc234",
        "https://ics.example.com/projects/abc234",
        "https://other.example.org/s/token",
        "[[abc234]]",
        "[[other:abc234]]",
    ],
)
def test_foreign_or_unrelated_links_ignored(text):
    assert extract_refs(text, BASE) == []


def test_base_url_host_is_case_insensitive_and_keeps_port():
    assert extract_refs("http://ICS.localhost:8080/v/abc", "http://ics.localhost:8080") == [
        Ref("slug", "abc")
    ]


def test_duplicates_collapsed():
    text = (
        "[[ics:abc]] ics://asset/abc https://ics.example.com/v/abc "
        "[[ics:abc|alias]] [[ics:abc/file.md]]"
    )
    assert extract_refs(text, BASE) == [Ref("slug", "abc"), Ref("slug", "abc", "file.md")]


def test_links_differing_only_by_version_are_one_reference():
    text = (
        "https://ics.example.com/v/abc?ver=1 https://ics.example.com/v/abc?ver=2 ics://asset/abc@v3"
    )
    assert extract_refs(text, BASE) == [Ref("slug", "abc")]


@pytest.mark.parametrize(
    "text",
    [
        "[[ics:abc234]]",
        "[[ ics:abc234 ]]",
        "[[ics:ABC234/dir/file.md#Heading one|Alias]]",
        "[[ics:abc234/dir/#anchor]]",
        "[[ics:abc234#a|b]]",
        "[[ics:abc-234]]",
        "[[ics:]]",
        "[[ics:abc[1]]]",
        "[[abc234]]",
    ],
)
def test_rendered_asset_link_yields_the_same_reference(text):
    """The renderer and the extractor share one `[[ics:...]]` grammar: a link
    renders as an asset link exactly when it yields an edge to that target."""
    html = render_markdown(text)
    refs = extract_refs(text, BASE)
    rendered = re.search(r'class="wikilink wikilink-ics" href="/v/([^"?#]+)', html)
    assert (rendered is not None) == bool(refs)
    if rendered is not None:
        assert refs == [refs[0]]
        assert rendered.group(1) == refs[0].value


def test_result_is_capped():
    text = " ".join(f"[[ics:s{i}]]" for i in range(MAX_REFS + 50))
    refs = extract_refs(text, BASE)
    assert len(refs) == MAX_REFS
    assert refs[0].value == "s0"


def test_module_is_pure():
    """The module must stay importable without settings or a database, so it
    can run anywhere (including subprocesses and pure unit tests)."""
    tree = ast.parse(inspect.getsource(relation_extract))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)
    forbidden = {"app.config", "app.db", "app.settings", "sqlalchemy"}
    assert not {
        name for name in imported if any(name == f or name.startswith(f + ".") for f in forbidden)
    }
    assert not any(name.startswith("app") for name in imported)
