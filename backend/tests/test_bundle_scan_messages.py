"""Scanner findings are stored as code + params and rendered per reader locale."""

from __future__ import annotations

import pytest

from app.bundle_scan import _scan_html, localize_report
from app.bundle_scan.scanner import ScanReport


def _stored(html: str) -> dict:
    """What `apply_scan_if_html` would persist for a single HTML file."""
    findings = _scan_html(
        "p.html", html, policy="strict", trusted_hosts=frozenset(), external_hosts=set()
    )
    return ScanReport(status="critical", findings=findings).to_dict()


def test_stored_findings_hold_codes_not_text():
    report = _stored('<script src="https://evil.cdn/x.js"></script><script>eval(x)</script>')
    for f in report["findings"]:
        assert "message" not in f
        assert f["code"]
    ext = next(f for f in report["findings"] if f["rule"] == "external_script_src")
    assert ext["params"] == {"host": "evil.cdn"}


@pytest.mark.parametrize(
    "locale,expected",
    [
        ("en", "<script src> from an external host: evil.cdn."),
        ("pl", "<script src> z zewnętrznego hosta: evil.cdn."),
    ],
)
def test_localize_report_renders_the_reader_locale(locale, expected):
    report = _stored('<script src="https://evil.cdn/x.js"></script>')
    out = localize_report(report, locale)
    assert out is not None
    assert out["findings"][0]["message"] == expected
    # The stored row stays text-free.
    assert "message" not in report["findings"][0]


def test_legacy_findings_without_codes():
    """Legacy rows without codes carry stored text and no params. Rules without parameters are re-rendered; the external-host
    rule keeps the stored text, since the host is only inside it."""
    legacy = {
        "status": "critical",
        "findings": [
            {
                "severity": "critical",
                "rule": "eval_call",
                "file": "a.js",
                "line": 1,
                "message": "Legacy eval() text.",
            },
            {
                "severity": "warn",
                "rule": "external_script_src",
                "file": "a.html",
                "line": 2,
                "message": "Legacy external host text: x.example.",
            },
            {
                "severity": "warn",
                "rule": "retired_rule",
                "file": "a.html",
                "line": 3,
                "message": "legacy description",
            },
        ],
    }
    out = localize_report(legacy, "en")
    assert out is not None
    messages = [f["message"] for f in out["findings"]]
    assert messages == [
        "eval() call: runs arbitrary code from a string.",
        "Legacy external host text: x.example.",
        "legacy description",
    ]


def test_localize_report_passes_empty_reports_through():
    assert localize_report(None, "pl") is None
    assert localize_report({}, "pl") == {}
