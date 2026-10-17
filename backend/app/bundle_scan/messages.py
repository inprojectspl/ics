"""Read-time text of stored scanner findings.

`Asset.security_report` keeps each finding's `code` and `params`; the
`message` field readers expect is rendered here, in the reader's locale.
"""

from __future__ import annotations

from typing import Any

from app.i18n import has_key, t, template_has_params


def _message(finding: dict[str, Any], locale: str) -> str | None:
    code = finding.get("code") or finding.get("rule", "")
    key = f"scan.{code}"
    stored = finding.get("message")
    params = finding.get("params")
    if not has_key(key):
        # Unknown code (a retired rule): the stored text, if any, is all there is.
        return None if stored is None else str(stored)
    if params is None:
        # A finding stored without params: its stored text is kept when the
        # message needs parameters (the external host is only inside it).
        if stored is not None and template_has_params(key):
            return str(stored)
        params = {}
    return t(key, locale, **params)


def localize_report(report: dict[str, Any] | None, locale: str) -> dict[str, Any] | None:
    """Copy of `report` with a `message` on every finding that has one. The
    stored row is not modified."""
    if not report:
        return report
    findings = []
    for f in report.get("findings", []):
        message = _message(f, locale)
        findings.append(f if message is None else {**f, "message": message})
    return {**report, "findings": findings}
