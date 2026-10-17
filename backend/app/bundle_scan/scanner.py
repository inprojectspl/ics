"""Scanner orchestration: runs the `_rules` over a bundle, aggregates the
results and writes them to `Asset.security_report`."""

from __future__ import annotations

import asyncio
from bisect import bisect_right
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from urllib.parse import urlparse

from app.collections_io import read_text
from app.config import Settings
from app.models import Asset
from app.storage import storage_from_url

from ._rules import (
    EXTERNAL_SCRIPT_RE,
    HREF_RE,
    HTML_RULES,
    INLINE_SCRIPT_CLOSE_RE,
    INLINE_SCRIPT_OPEN_RE,
    JS_RULES,
    SVG_CLOSE_RE,
    SVG_INNER_SCRIPT_RE,
    SVG_OPEN_RE,
    SVG_SCRIPT_RULE,
    Finding,
    Policy,
    Status,
    severity_for,
)


@dataclass
class ScanReport:
    status: Status
    findings: list[Finding]
    external_hosts: list[str] | None = None  # unique external script hosts seen

    def to_dict(self) -> dict:
        d: dict = {
            "status": self.status,
            "findings": [asdict(f) for f in self.findings],
        }
        if self.external_hosts is not None:
            d["external_hosts"] = self.external_hosts
        return d


# Storage reads run concurrently but bounded: a bundle can hold hundreds
# of scannable files.
_READ_CONCURRENCY = 16


def _host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def _newline_offsets(text: str) -> list[int]:
    """Offsets of every newline, ascending: the index `_line_at` bisects."""
    offsets: list[int] = []
    start = 0
    while (idx := text.find("\n", start)) != -1:
        offsets.append(idx)
        start = idx + 1
    return offsets


def _line_at(offsets: list[int], pos: int) -> int:
    """1-based line number for `pos`; a bisect keeps many hits on a minified
    page linear instead of rescanning for newlines per match."""
    return bisect_right(offsets, pos - 1) + 1


def _iter_inline_scripts(text: str) -> Iterator[tuple[int, str]]:
    """Yield `(offset, block)` for every inline `<script>` without `src`;
    one without `</script>` is skipped (see `INLINE_SCRIPT_OPEN_RE`)."""
    pos = 0
    while (open_m := INLINE_SCRIPT_OPEN_RE.search(text, pos)) is not None:
        close_m = INLINE_SCRIPT_CLOSE_RE.search(text, open_m.end())
        if close_m is None:
            return
        yield open_m.start(), text[open_m.start() : close_m.start()]
        pos = close_m.end()


def _iter_svg_scripts(text: str) -> Iterator[int]:
    """Yield the offset of every `<svg>` that contains a `<script>`; a missing
    `</svg>` means the body runs to the end of the file."""
    pos = 0
    while (open_m := SVG_OPEN_RE.search(text, pos)) is not None:
        close_m = SVG_CLOSE_RE.search(text, open_m.end())
        body_end = close_m.start() if close_m is not None else len(text)
        inner = SVG_INNER_SCRIPT_RE.search(text, open_m.end(), body_end)
        if inner is not None:
            yield open_m.start()
        pos = close_m.end() if close_m is not None else len(text)


def _scan_html(
    path: str,
    text: str,
    *,
    policy: Policy,
    trusted_hosts: frozenset[str],
    external_hosts: set[str],
) -> list[Finding]:
    out: list[Finding] = []
    lines = _newline_offsets(text)
    for rule in HTML_RULES:
        for m in rule.pattern.finditer(text):
            out.append(
                Finding(
                    severity_for(rule.name, policy=policy),
                    rule.name,
                    path,
                    _line_at(lines, m.start()),
                )
            )
    for svg_pos in _iter_svg_scripts(text):
        out.append(
            Finding(
                severity_for(SVG_SCRIPT_RULE, policy=policy),
                SVG_SCRIPT_RULE,
                path,
                _line_at(lines, svg_pos),
            )
        )
    for m in EXTERNAL_SCRIPT_RE.finditer(text):
        url = m.group(1)
        host = _host_of(url)
        if host:
            external_hosts.add(host)
        sev = severity_for(
            "external_script_src",
            policy=policy,
            host=host,
            trusted_hosts=trusted_hosts,
        )
        trusted = sev == "info" and policy == "permissive"
        out.append(
            Finding(
                sev,
                "external_script_src",
                path,
                _line_at(lines, m.start()),
                params={"host": host or url},
                code="external_script_src_trusted" if trusted else "external_script_src",
            )
        )
    for offset, body in _iter_inline_scripts(text):
        base_line = _line_at(lines, offset)
        out.extend(_scan_js_body(path, body, base_line - 1, policy=policy))
    return out


def link_hrefs(text: str) -> list[str]:
    """`href` values of `<a>`, `<area>` and `<link>` in an HTML page, in
    document order, with the same tag matching the scan rules use."""
    return [next(g for g in m.groups() if g is not None) for m in HREF_RE.finditer(text)]


def _scan_js_body(
    path: str,
    text: str,
    line_offset: int = 0,
    *,
    policy: Policy,
) -> list[Finding]:
    out: list[Finding] = []
    lines = _newline_offsets(text)
    for rule in JS_RULES:
        for m in rule.pattern.finditer(text):
            out.append(
                Finding(
                    severity_for(rule.name, policy=policy),
                    rule.name,
                    path,
                    _line_at(lines, m.start()) + line_offset,
                )
            )
    return out


def _scan_file(
    path: str,
    text: str,
    *,
    policy: Policy,
    trusted_hosts: frozenset[str],
    external_hosts: set[str],
) -> list[Finding]:
    lower = path.lower()
    if lower.endswith((".html", ".htm")):
        return _scan_html(
            path,
            text,
            policy=policy,
            trusted_hosts=trusted_hosts,
            external_hosts=external_hosts,
        )
    if lower.endswith((".js", ".mjs")):
        return _scan_js_body(path, text, policy=policy)
    return []


def _aggregate(findings: list[Finding]) -> Status:
    if any(f.severity == "critical" for f in findings):
        return "critical"
    if any(f.severity == "warn" for f in findings):
        return "warn"
    return "clean"


async def scan_bundle(
    asset: Asset,
    settings: Settings,
    *,
    trusted_hosts: frozenset[str] | None = None,
) -> ScanReport:
    """Scan the HTML/JS files of the asset's current version. `trusted_hosts`
    defaults to the env baseline; callers with a DB session should pass
    `app.cdn_allowlist.trusted_hosts(...)` to include admin-added hosts."""
    policy: Policy = "strict" if settings.security_policy == "strict" else "permissive"
    if trusted_hosts is None:
        trusted_hosts = settings.trusted_cdn_hosts_set

    storage = storage_from_url(settings.storage_url)
    prefix = f"{asset.storage_prefix}/v{asset.version}/"
    keys = await storage.list_prefix(prefix)

    scannable = [
        key[len(prefix) :]
        for key in keys
        if key[len(prefix) :].lower().endswith((".html", ".htm", ".js", ".mjs"))
    ]
    sem = asyncio.Semaphore(_READ_CONCURRENCY)

    async def _read(rel: str) -> tuple[str, str] | None:
        async with sem:
            try:
                return rel, await read_text(asset, rel, settings)
            except FileNotFoundError:
                return None

    sources = await asyncio.gather(*(_read(rel) for rel in scannable))

    external_hosts: set[str] = set()

    def _scan_all() -> list[Finding]:
        # Pure CPU over megabytes of HTML: off the event loop.
        out: list[Finding] = []
        for source in sources:
            if source is None:
                continue
            rel, text = source
            out.extend(
                _scan_file(
                    rel,
                    text,
                    policy=policy,
                    trusted_hosts=trusted_hosts,
                    external_hosts=external_hosts,
                )
            )
        return out

    findings = await asyncio.to_thread(_scan_all)

    return ScanReport(
        status=_aggregate(findings),
        findings=findings,
        external_hosts=sorted(external_hosts),
    )


async def apply_scan_if_html(
    asset: Asset,
    settings: Settings,
    *,
    trusted_hosts: frozenset[str] | None = None,
) -> dict | None:
    """Scan an html_bundle asset and store the result (`apply_report`);
    returns the audit summary, or None for other kinds."""
    if asset.kind != "html_bundle":
        return None
    return apply_report(asset, await scan_bundle(asset, settings, trusted_hosts=trusted_hosts))


def report_of(findings: list[Finding]) -> ScanReport:
    return ScanReport(status=_aggregate(findings), findings=findings)


def apply_report(asset: Asset, report: ScanReport) -> dict:
    """Store a scan result on the asset row and return the audit summary.

    Resets any admin bypass: it approved a specific set of findings, so a
    rescanned critical upload must re-enter the review queue.
    """
    asset.security_status = report.status
    asset.security_report = report.to_dict()
    asset.security_bypass = False
    asset.security_bypass_at = None
    asset.security_bypass_by = None
    asset.security_bypass_reason = None
    return {
        "status": report.status,
        "critical_count": sum(1 for f in report.findings if f.severity == "critical"),
        "warn_count": sum(1 for f in report.findings if f.severity == "warn"),
        "external_hosts": report.external_hosts or [],
    }
