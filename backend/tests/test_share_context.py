"""Copyable addresses: `ics_share` rules, page targets and head injection."""

import pytest

from app.services.share_context import (
    clean_target,
    head_insert_at,
    inject_head,
    read_token,
    recovery_page,
    script_tag,
    target_url,
    with_token,
)

T = "A" * 43
B = "B" * 43


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("", ("none", None)),
        ("tab=2", ("none", None)),
        (f"ics_share={T}", ("one", T)),
        (f"lang=pl&ics_share={T}&x=1", ("one", T)),
        (f"ics%5Fshare={T}", ("one", T)),
        # Repeated, even with the same value, is ambiguous.
        (f"ics_share={T}&ics_share={T}", ("invalid", None)),
        (f"ics_share={T}&ics_share={B}", ("invalid", None)),
        ("ics_share=short", ("invalid", None)),
        ("ics_share=", ("invalid", None)),
        ("ics_share=" + "A" * 129, ("invalid", None)),
        (f"ics_share={T}%22", ("invalid", None)),
    ],
)
def test_read_token(query, expected):
    assert read_token(query) == expected


@pytest.mark.parametrize(
    ("query", "token", "expected"),
    [
        ("", T, f"ics_share={T}"),
        ("tab=2&a=%20b&a=c", T, f"tab=2&a=%20b&a=c&ics_share={T}"),
        (f"ics_share={B}&tab=2", T, f"tab=2&ics_share={T}"),
        (f"tab=2&ics_share={B}", None, "tab=2"),
        ("x=1&&y", None, "x=1&y"),
    ],
)
def test_with_token_keeps_other_parameters_verbatim(query, token, expected):
    assert with_token(query, token) == expected


@pytest.mark.parametrize(
    ("to", "expected"),
    [
        ("index.html", "index.html"),
        ("sub/page.html?tab=wyniki&x=%2F", "sub/page.html?tab=wyniki&x=%2F"),
        (f"page.html?ics_share={T}&tab=2", "page.html?tab=2"),
        ("dir/", "dir/"),
        ("", None),
        (None, None),
        ("/page.html", None),
        ("//evil.example/x.html", None),
        ("%2F%2Fevil.example/x.html", None),
        ("../other/index.html", None),
        ("a/%2e%2e/b.html", None),
        ("a/%252e%252e/b.html", None),
        ("a//b.html", None),
        ("a\\b.html", None),
        ("a%5Cb.html", None),
        ("page.html\n", None),
        ("page%0d.html", None),
        ("page.html#frag", None),
        ("x" * 2049, None),
    ],
)
def test_clean_target_stays_inside_the_asset(to, expected):
    assert clean_target(to) == expected


def test_target_url_puts_the_token_before_the_fragment_and_last():
    assert target_url("/slug", "a.html?tab=2", T) == f"/slug/a.html?tab=2&ics_share={T}"
    assert target_url("/-v2/slug", "", None) == "/-v2/slug/"
    assert target_url("/slug", "index.html", T) == f"/slug/index.html?ics_share={T}"


SNIP = "<script data-x></script>"


@pytest.mark.parametrize(
    ("raw", "marker"),
    [
        # After the charset declaration, before everything else.
        (b'<!doctype html><html><head><meta charset="utf-8"><title>x</title>', b"<title>"),
        # No charset: before the page's first script.
        (b"<!DOCTYPE html><head><title>a</title><script src=app.js></script>", b"<script src"),
        (b"<html><head><link rel=x href=a><style>p{}</style><script>1</script>", b"<script>1"),
        # A comment holding a fake <head> or script is skipped.
        (b"<!-- <head><script> --><html><head><script>x</script>", b"<script>x"),
        # No head at all: before the first content.
        (b"<!doctype html><script>early()</script><p>x</p>", b"<script>early"),
        (b"<p>fragment</p>", b"<p>"),
        # Empty head: before </head>.
        (b"<html><head></head><body>", b"</head>"),
        # Attribute values with '>' do not end the tag early.
        (b'<head><meta name="a>b" content=x><script>1</script>', b"<script>1"),
        (b"<head><title>a <script> b</title><script>2</script>", b"<script>2"),
        (b'<head><meta http-equiv="Content-Type" content="text/html; charset=x"><b>', b"<b>"),
    ],
)
def test_head_insert_lands_before_the_marker(raw, marker):
    out = inject_head(raw, SNIP)
    assert out.count(SNIP.encode()) == 1
    assert out.index(SNIP.encode()) + len(SNIP) == out.index(marker)


def test_head_insert_keeps_the_bom_first():
    raw = b"\xef\xbb\xbf<!doctype html><script>1</script>"
    assert inject_head(raw, SNIP).startswith(b"\xef\xbb\xbf<!doctype html>" + SNIP.encode())


def test_head_insert_of_an_unterminated_comment_goes_before_it():
    assert head_insert_at(b"<!-- never closed <script>") == 0


def test_script_tag_escapes_and_stays_ascii():
    tag = script_tag("https://h.test/_/s.js", asset_id='a"b', scope="/żółw/", launch=None)
    assert tag.isascii()
    assert 'data-asset-id="a&quot;b"' in tag
    assert "data-launch" not in tag
    assert tag.endswith("></script>")


def test_recovery_page_has_no_asset_content():
    page = recovery_page(lang="pl", title="T<", message="M&", script_html=SNIP)
    assert b"<title>T&lt;</title>" in page
    assert b"<p>M&amp;</p>" in page
    assert SNIP.encode() in page
