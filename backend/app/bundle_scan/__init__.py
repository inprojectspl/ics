"""Layer 2 scanner: static analysis of uploaded content. Rules are in
`_rules`, the scan flow in `scanner`, locale-rendered finding text in
`messages`. The private helpers are re-exported for tests."""

from app.bundle_scan._rules import Finding
from app.bundle_scan.messages import localize_report
from app.bundle_scan.scanner import (
    _aggregate,
    _scan_file,
    _scan_html,
    _scan_js_body,
    apply_report,
    apply_scan_if_html,
    link_hrefs,
    report_of,
    scan_bundle,
)

__all__ = [
    "Finding",
    "_aggregate",
    "_scan_file",
    "_scan_html",
    "_scan_js_body",
    "apply_report",
    "apply_scan_if_html",
    "link_hrefs",
    "localize_report",
    "report_of",
    "scan_bundle",
]
