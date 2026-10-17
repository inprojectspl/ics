"""The "archived version" banner injected into served HTML.

Requirements these tests pin down (and that a refactor easily breaks):
- the snippet is ASCII-only, since a bundle may declare a charset other than UTF-8,
- we insert it after `<body>`, in normal flow (no `position:fixed`), but with
  the maximum `z-index` so the page CSS does not cover it,
- document bytes outside the insertion point stay untouched (we do not
  re-encode pages in another charset).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.services.version_banner import build_banner_html, inject_banner


def _banner(locale: str = "en") -> str:
    return build_banner_html(
        preview_version=2,
        current_version=5,
        preview_created_at=datetime(2026, 1, 2, 10, 30, tzinfo=UTC),
        current_updated_at=datetime(2026, 3, 4, 8, 15, tzinfo=UTC),
        locale=locale,
    )


def test_banner_is_ascii_only():
    """Polish characters must come out as numeric entities, otherwise a page
    with `charset=iso-8859-2` would show mojibake in the warning."""
    snippet = _banner("pl")
    snippet.encode("ascii")  # would raise UnicodeEncodeError
    assert "&#261;" in snippet  # "ą" from "Podglądasz"


@pytest.mark.parametrize(
    "locale,text,close",
    [
        ("en", "You are viewing archived version v2 from 2026-01-02 10:30", "Close"),
        ("pl", "Podgl&#261;dasz archiwaln&#261; wersj&#281; v2 z 2026-01-02 10:30", "Zamknij"),
    ],
)
def test_banner_text_follows_locale(locale, text, close):
    snippet = _banner(locale)
    assert text in snippet
    assert f'aria-label="{close}"' in snippet


def test_banner_mentions_both_versions_and_dates():
    snippet = _banner()
    assert "v2" in snippet
    assert "v5" in snippet
    assert "2026-01-02 10:30" in snippet
    assert "2026-03-04 08:15" in snippet


def test_banner_is_static_in_flow_with_max_z_index():
    snippet = _banner()
    assert "position:relative!important" in snippet
    assert "position:fixed" not in snippet
    assert "position:sticky" not in snippet
    assert "z-index:2147483647!important" in snippet


def test_banner_has_dismiss_button():
    snippet = _banner()
    assert "<button" in snippet
    assert "removeChild" in snippet


def test_banner_without_dates_still_renders():
    snippet = build_banner_html(preview_version=1, current_version=3, locale="en")
    snippet.encode("ascii")
    assert "v1" in snippet and "v3" in snippet


def test_inject_after_body_tag():
    raw = b"<html><head><title>x</title></head><body class='a'><h1>Hi</h1></body></html>"
    out = inject_banner(raw, "<div>BANNER</div>")
    assert out.index(b"BANNER") > out.index(b"<body class='a'>")
    assert out.index(b"BANNER") < out.index(b"<h1>")


def test_inject_after_head_when_no_body():
    raw = b"<html><head><title>x</title></head><p>frag</p></html>"
    out = inject_banner(raw, "<div>BANNER</div>")
    assert out.index(b"BANNER") > out.index(b"</head>")
    assert out.index(b"BANNER") < out.index(b"<p>")


def test_inject_prepends_for_bare_fragment():
    raw = b"<p>just a fragment</p>"
    out = inject_banner(raw, "<div>BANNER</div>")
    assert out.startswith(b"<div>BANNER</div>")
    assert out.endswith(raw)


def test_inject_is_case_insensitive_on_body():
    raw = b"<HTML><BODY><p>x</p></BODY></HTML>"
    out = inject_banner(raw, "<div>BANNER</div>")
    assert out.index(b"BANNER") > out.index(b"<BODY>")


def test_inject_preserves_non_utf8_bytes():
    """A page in iso-8859-2 (0xB1 = "ą") passes through bit for bit."""
    raw = b"<html><body>za\xb3\xb1cznik</body></html>"
    out = inject_banner(raw, "<div>BANNER</div>")
    assert b"za\xb3\xb1cznik" in out
    assert len(out) == len(raw) + len(b"<div>BANNER</div>")


def test_inject_only_touches_first_body():
    raw = b"<body>one</body><body>two</body>"
    out = inject_banner(raw, "<div>B</div>")
    assert out.count(b"<div>B</div>") == 1
