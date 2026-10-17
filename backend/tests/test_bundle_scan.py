"""Layer 2 static analysis: regex-level smell detection and end-to-end
storage scan."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.bundle_scan import (
    Finding,
    _aggregate,
    apply_scan_if_html,
    scan_bundle,
)
from app.bundle_scan import (
    _scan_file as _scan_file_impl,
)
from app.bundle_scan import (
    _scan_html as _scan_html_impl,
)
from app.bundle_scan import (
    _scan_js_body as _scan_js_body_impl,
)

# Default policy for the scan-helper tests: strict. Tests that exercise the
# permissive policy pass it explicitly.
_DEFAULT_POLICY = "strict"
_DEFAULT_TRUSTED: frozenset[str] = frozenset()


def _scan_html(
    path, text, *, policy=_DEFAULT_POLICY, trusted_hosts=_DEFAULT_TRUSTED, external_hosts=None
):
    return _scan_html_impl(
        path,
        text,
        policy=policy,
        trusted_hosts=trusted_hosts,
        external_hosts=external_hosts if external_hosts is not None else set(),
    )


def _scan_js_body(path, text, line_offset=0, *, policy=_DEFAULT_POLICY):
    return _scan_js_body_impl(path, text, line_offset, policy=policy)


def _scan_file(
    path, text, *, policy=_DEFAULT_POLICY, trusted_hosts=_DEFAULT_TRUSTED, external_hosts=None
):
    return _scan_file_impl(
        path,
        text,
        policy=policy,
        trusted_hosts=trusted_hosts,
        external_hosts=external_hosts if external_hosts is not None else set(),
    )


# ---------- HTML scanner ----------


def _rules(findings: list[Finding]) -> set[str]:
    return {f.rule for f in findings}


def test_html_javascript_protocol_critical():
    out = _scan_html("p.html", '<a href="javascript:alert(1)">x</a>')
    assert any(f.rule == "javascript_protocol" and f.severity == "critical" for f in out)


def test_html_data_url_html_critical():
    out = _scan_html("p.html", '<iframe src="data:text/html,<script>alert(1)</script>"></iframe>')
    assert any(f.rule == "data_url_active" and f.severity == "critical" for f in out)


def test_html_external_script_src_critical():
    out = _scan_html("p.html", '<script src="https://evil.cdn/x.js"></script>')
    crit = [f for f in out if f.rule == "external_script_src"]
    assert crit and crit[0].severity == "critical"
    assert crit[0].params == {"host": "evil.cdn"}
    assert crit[0].code == "external_script_src"


def test_html_inline_event_handler_warn():
    out = _scan_html("p.html", '<button onclick="doIt()">go</button>')
    assert any(f.rule == "inline_event_handler" and f.severity == "warn" for f in out)


def test_html_meta_refresh_warn():
    out = _scan_html(
        "p.html",
        '<meta http-equiv="refresh" content="0;url=https://evil.example/">',
    )
    assert any(f.rule == "meta_refresh" and f.severity == "warn" for f in out)


def test_html_meta_refresh_case_insensitive():
    out = _scan_html(
        "p.html",
        '<META HTTP-EQUIV="REFRESH" CONTENT="2;URL=https://evil.example">',
    )
    assert any(f.rule == "meta_refresh" for f in out)


def test_html_svg_script_critical():
    """An SVG-embedded <script> runs in the parent document's context,
    a critical bypass of the per-file scanner."""
    out = _scan_html(
        "p.html",
        '<svg width="100" height="100"><script>alert(1)</script></svg>',
    )
    crit = [f for f in out if f.rule == "svg_script"]
    assert crit and crit[0].severity == "critical"


def test_html_plain_svg_without_script_is_clean():
    """Regression: an <svg> without a <script> inside must not be flagged."""
    out = _scan_html(
        "p.html",
        '<svg><circle cx="50" cy="50" r="40" fill="red"/></svg>',
    )
    assert not any(f.rule == "svg_script" for f in out)


@pytest.mark.parametrize(
    ("label", "html", "expected_lines"),
    [
        ("unclosed svg", "<svg><script>x</script>", [1]),
        (
            "two separate svgs",
            "<svg><script>a</script></svg><p>x</p><svg><script>b</script></svg>",
            [1, 1],
        ),
        ("script before svg", "<script>a</script><svg><circle/></svg>", []),
        ("script after svg", "<svg><circle/></svg><script>x</script>", []),
        ("uppercase", "<SVG><SCRIPT>x</SCRIPT></SVG>", [1]),
        ("space in closing tag", "<svg><script>x</script></svg >", [1]),
        ("nested svg", "<svg><g><svg><script>x</script></svg></g></svg>", [1]),
        ("svg with attributes", '<svg xmlns="http://a" viewBox="0 0 1 1"><script/></svg>', [1]),
        ("multiline", "<html>\n<svg>\n<script>\nx\n</script>\n</svg>\n", [2]),
        ("< in text", "<svg><text>a < b</text><script>x</script></svg>", [1]),
    ],
)
def test_html_svg_script_edge_cases(label: str, html: str, expected_lines: list[int]):
    """The `<svg>` scan walks indices instead of running one regex over the
    body, which used more than a gigabyte of RAM on a large inline SVG.
    These cases pin what it finds, what it does not, and on which line."""
    out = _scan_html("p.html", html)
    assert [f.line for f in out if f.rule == "svg_script"] == expected_lines, label


def test_html_script_after_svg_closed_with_space_is_not_svg_script():
    """`</svg >` closes the element, so the following `<script>` is a plain
    inline script, not a script embedded in SVG.

    Requiring exactly `</svg>` would keep scanning past the space before
    `>` and produce a critical finding on a valid file.
    The script body itself still goes through the JS rules."""
    doc = "<svg><circle/></svg ><script>eval(x)</script>"
    out = _scan_html("p.html", doc)
    assert not any(f.rule == "svg_script" for f in out)
    assert any(f.rule == "eval_call" for f in out)


def test_html_line_numbers_on_minified_single_line():
    """Line numbers come from a bisect over offsets, not from recounting
    the text from the start on every match. A minified page is a single
    line, so every match must report line 1."""
    html = "<html><body>" + "".join(f'<div onclick="f({i})">x</div>' for i in range(50))
    out = _scan_html("p.html", html)
    handlers = [f for f in out if f.rule == "inline_event_handler"]
    assert len(handlers) == 50
    assert {f.line for f in handlers} == {1}


def test_html_line_numbers_across_lines():
    html = "<p>a</p>\n<p onclick='x'>b</p>\n\n<p onclick='y'>c</p>"
    out = _scan_html("p.html", html)
    assert [f.line for f in out if f.rule == "inline_event_handler"] == [2, 4]


def test_html_inline_script_eval_propagates_critical():
    # `eval(...)` inside inline <script>: the HTML scanner descends into the
    # script body and the inner rule fires at the right line offset.
    out = _scan_html(
        "p.html", "<html>\n<head></head>\n<body>\n<script>\neval(x)\n</script>\n</body></html>"
    )
    eval_findings = [f for f in out if f.rule == "eval_call"]
    assert eval_findings and eval_findings[0].severity == "critical"
    assert eval_findings[0].line == 5  # `eval(x)` is on line 5 of the HTML


def test_html_inline_script_on_one_huge_line_stays_bounded():
    """A minified bundle (all HTML on one line) must stay within memory.
    Matching the `<script>` body with `(?:.|\n)*?` stores backtracking
    context for every body character: 7.6 MB on one line gave ~900 MB RSS.
    Index-based extraction keeps it at the input size.
    """
    padding = "var a = 1; " * 200_000  # ~2.2 MB on one line
    html = f"<html><body><script>{padding}eval(x)</script></body></html>"
    out = _scan_html("big.html", html)
    assert [f.rule for f in out if f.severity == "critical"] == ["eval_call"]
    assert out[0].line == 1


def test_html_multiple_inline_scripts_all_scanned():
    # The second block must not get lost after leaving the first.
    out = _scan_html(
        "p.html",
        "<html><script>eval(a)</script><p>x</p><script>eval(b)</script></html>",
    )
    assert len([f for f in out if f.rule == "eval_call"]) == 2


def test_html_inline_script_with_src_is_not_body_scanned():
    # `<script src=...>` is handled by the external_script_src rule; its
    # (empty) body is not scanned as inline JS.
    out = _scan_html(
        "p.html",
        '<html><script src="https://cdn.example.com/a.js">eval(x)</script></html>',
    )
    assert not any(f.rule == "eval_call" for f in out)


def test_html_unterminated_inline_script_is_skipped():
    # An unterminated `<script>` is not scanned as inline JS.
    out = _scan_html("p.html", "<html><script>eval(x)")
    assert not any(f.rule == "eval_call" for f in out)


def test_html_clean_doc_is_clean():
    assert _scan_html("p.html", "<html><body><h1>safe</h1><p>hello</p></body></html>") == []


# ---------- JS scanner ----------


def test_js_eval_critical():
    out = _scan_js_body("a.js", "var x = eval(payload);")
    assert any(f.rule == "eval_call" and f.severity == "critical" for f in out)


def test_js_new_function_critical():
    out = _scan_js_body("a.js", "const f = new Function('return 1');")
    assert any(f.rule == "new_function" and f.severity == "critical" for f in out)


def test_js_document_write_warn():
    out = _scan_js_body("a.js", "document.write('<b>hi</b>')")
    assert any(f.rule == "document_write" and f.severity == "warn" for f in out)


def test_js_settimeout_string_warn():
    out = _scan_js_body("a.js", 'setTimeout("alert(1)", 100);')
    assert any(f.rule == "timer_string_arg" and f.severity == "warn" for f in out)


def test_js_settimeout_function_not_flagged():
    # Function (not string) as first arg -> no finding.
    out = _scan_js_body("a.js", "setTimeout(() => alert(1), 100);")
    assert not any(f.rule == "timer_string_arg" for f in out)


def test_js_loopback_fetch_warn():
    out = _scan_js_body("a.js", 'fetch("http://127.0.0.1:8000/x")')
    assert any(f.rule == "loopback_fetch" and f.severity == "warn" for f in out)


def test_js_clean_is_clean():
    assert _scan_js_body("a.js", "const x = 1 + 2;") == []


# ---------- dispatcher ----------


def test_scan_file_skips_non_text_kinds():
    assert _scan_file("img/logo.png", "eval(x)") == []
    assert _scan_file("style.css", "body { background: url('javascript:1') }") == []


def test_scan_file_dispatches_html_vs_js():
    html_out = _scan_file("page.html", '<button onclick="x">')
    assert _rules(html_out) == {"inline_event_handler"}
    js_out = _scan_file("module.mjs", "eval(x)")
    assert _rules(js_out) == {"eval_call"}


# ---------- aggregation ----------


def test_aggregate_empty_is_clean():
    assert _aggregate([]) == "clean"


def test_aggregate_warn_only():
    fs = [Finding("warn", "r", "f", 1)]
    assert _aggregate(fs) == "warn"


def test_aggregate_critical_wins_over_warn():
    fs = [
        Finding("warn", "r1", "f", 1),
        Finding("critical", "r2", "f", 2),
        Finding("info", "r3", "f", 3),
    ]
    assert _aggregate(fs) == "critical"


# ---------- end-to-end via storage ----------


@pytest.mark.asyncio
async def test_scan_bundle_end_to_end(tmp_path: Path):
    # Build an on-disk bundle that mimics the storage layout:
    #   assets/abc/v1/{index.html,app.js,style.css}
    prefix = tmp_path / "assets" / "abc" / "v1"
    prefix.mkdir(parents=True)
    (prefix / "index.html").write_text('<a href="javascript:1">x</a>', encoding="utf-8")
    (prefix / "app.js").write_text("document.write('x')", encoding="utf-8")
    (prefix / "style.css").write_text(".x { color: red }", encoding="utf-8")  # ignored

    asset = SimpleNamespace(
        storage_prefix="assets/abc",
        version=1,
        kind="html_bundle",
    )
    settings = SimpleNamespace(
        storage_url=f"fs://{tmp_path}",
        security_policy="strict",
        trusted_cdn_hosts="",
        trusted_cdn_hosts_set=frozenset(),
    )
    report = await scan_bundle(asset, settings)

    assert report.status == "critical"  # javascript: protocol wins
    rules_by_file = {f.file: f.rule for f in report.findings}
    assert rules_by_file == {
        "index.html": "javascript_protocol",
        "app.js": "document_write",
    }


@pytest.mark.asyncio
async def test_scan_bundle_empty_clean(tmp_path: Path):
    prefix = tmp_path / "assets" / "abc" / "v1"
    prefix.mkdir(parents=True)
    (prefix / "index.html").write_text("<h1>safe</h1>", encoding="utf-8")
    asset = SimpleNamespace(storage_prefix="assets/abc", version=1, kind="html_bundle")
    settings = SimpleNamespace(
        storage_url=f"fs://{tmp_path}",
        security_policy="strict",
        trusted_cdn_hosts="",
        trusted_cdn_hosts_set=frozenset(),
    )
    report = await scan_bundle(asset, settings)
    assert report.status == "clean"
    assert report.findings == []


# ---------- apply_scan_if_html wrapper ----------


@pytest.mark.asyncio
async def test_apply_scan_writes_to_asset(tmp_path: Path):
    prefix = tmp_path / "assets" / "abc" / "v1"
    prefix.mkdir(parents=True)
    (prefix / "index.html").write_text('<a href="javascript:1">x</a>', encoding="utf-8")
    asset = SimpleNamespace(
        storage_prefix="assets/abc",
        version=1,
        kind="html_bundle",
        security_status=None,
        security_report=None,
    )
    settings = SimpleNamespace(
        storage_url=f"fs://{tmp_path}",
        security_policy="strict",
        trusted_cdn_hosts="",
        trusted_cdn_hosts_set=frozenset(),
    )
    summary = await apply_scan_if_html(asset, settings)

    assert asset.security_status == "critical"
    assert asset.security_report["status"] == "critical"
    assert summary["status"] == "critical"
    assert summary["critical_count"] == 1
    assert summary["warn_count"] == 0
    assert summary["external_hosts"] == []


# ---------- permissive policy + CDN allowlist ----------


def test_permissive_external_script_trusted_cdn_is_info():
    """`cdn.jsdelivr.net` on the trusted set -> info, not blocking."""
    trusted = frozenset({"cdn.jsdelivr.net"})
    out = _scan_html(
        "page.html",
        '<script src="https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"></script>',
        policy="permissive",
        trusted_hosts=trusted,
    )
    ext = [f for f in out if f.rule == "external_script_src"]
    assert ext and ext[0].severity == "info"
    assert ext[0].code == "external_script_src_trusted"


def test_permissive_external_script_unknown_host_is_warn():
    out = _scan_html(
        "page.html",
        '<script src="https://evil.example.com/payload.js"></script>',
        policy="permissive",
        trusted_hosts=frozenset({"cdn.jsdelivr.net"}),
    )
    ext = [f for f in out if f.rule == "external_script_src"]
    assert ext and ext[0].severity == "warn"


def test_strict_external_script_stays_critical():
    """`strict` keeps the hard line: every external script blocks."""
    out = _scan_html(
        "page.html",
        '<script src="https://cdn.jsdelivr.net/npm/x.js"></script>',
        policy="strict",
        trusted_hosts=frozenset({"cdn.jsdelivr.net"}),
    )
    ext = [f for f in out if f.rule == "external_script_src"]
    assert ext and ext[0].severity == "critical"


def test_permissive_inline_event_handler_is_info():
    out = _scan_html("p.html", '<button onclick="doIt()">go</button>', policy="permissive")
    flagged = [f for f in out if f.rule == "inline_event_handler"]
    assert flagged and flagged[0].severity == "info"


def test_permissive_document_write_is_info():
    out = _scan_js_body("a.js", "document.write('hi')", policy="permissive")
    assert any(f.rule == "document_write" and f.severity == "info" for f in out)


def test_permissive_eval_stays_critical():
    out = _scan_js_body("a.js", "eval(payload)", policy="permissive")
    assert any(f.rule == "eval_call" and f.severity == "critical" for f in out)


def test_document_cookie_is_critical_in_both_policies():
    for policy in ("permissive", "strict"):
        out = _scan_js_body("a.js", "fetch('/exfil?c='+document.cookie)", policy=policy)
        cookie = [f for f in out if f.rule == "document_cookie"]
        assert cookie and cookie[0].severity == "critical", policy


@pytest.mark.asyncio
async def test_scan_bundle_collects_external_hosts(tmp_path: Path):
    prefix = tmp_path / "assets" / "x" / "v1"
    prefix.mkdir(parents=True)
    (prefix / "index.html").write_text(
        '<script src="https://cdn.jsdelivr.net/x.js"></script>'
        '<script src="https://unpkg.com/y.js"></script>'
        '<script src="https://cdn.jsdelivr.net/z.js"></script>',  # duplicate host
        encoding="utf-8",
    )
    settings = SimpleNamespace(
        storage_url=f"fs://{tmp_path}",
        security_policy="permissive",
        trusted_cdn_hosts="cdn.jsdelivr.net,unpkg.com",
        trusted_cdn_hosts_set=frozenset({"cdn.jsdelivr.net", "unpkg.com"}),
    )
    asset = SimpleNamespace(storage_prefix="assets/x", version=1, kind="html_bundle")
    report = await scan_bundle(asset, settings)
    # Both hosts trusted -> status clean. Hosts deduplicated.
    assert report.status == "clean"
    assert report.external_hosts == ["cdn.jsdelivr.net", "unpkg.com"]


@pytest.mark.asyncio
async def test_apply_scan_skips_non_html_kinds(tmp_path: Path):
    asset = SimpleNamespace(
        storage_prefix="assets/abc",
        version=1,
        kind="md_collection",
        security_status="clean",
        security_report=None,
    )
    settings = SimpleNamespace(
        storage_url=f"fs://{tmp_path}",
        security_policy="strict",
        trusted_cdn_hosts="",
        trusted_cdn_hosts_set=frozenset(),
    )
    summary = await apply_scan_if_html(asset, settings)

    # No-op for md kinds: neither writes nor returns a summary.
    assert summary is None
    assert asset.security_status == "clean"
    assert asset.security_report is None
