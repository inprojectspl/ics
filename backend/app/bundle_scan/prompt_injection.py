"""Prompt-injection heuristic for Markdown and extracted document text.

Advisory only (`warn`, never blocks publication). Patterns are narrow so
prose such as "ignore the cache" stays clean. Polish letters are escapes
because source is English-only (ADR-0009).
"""

from __future__ import annotations

import asyncio
import re

from app.collections_io import MarkdownSources, read_markdown_files
from app.config import Settings
from app.models import Asset

from ._rules import Finding
from .scanner import ScanReport, _line_at, _newline_offsets, report_of

RULE = "prompt_injection_suspect"
# One document full of hits needs no more than a sample in the report.
MAX_FINDINGS_PER_FILE = 10
_PHRASE_CHARS = 80

_EARLIER_EN = r"(?:previous|prior|preceding|earlier|above|former)"
_ORDERS_EN = (
    r"(?:instructions?|prompts?|directions?|directives?|commands?|rules|guidelines|"
    r"context|messages?)"
)
_EARLIER_PL = r"(?:poprzedni\w*|wcze[s\u015b]niejsz\w*|powy[z\u017c]sz\w*|dotychczasow\w*)"
_ORDERS_PL = r"(?:instrukcj\w*|polece\w*|wytyczn\w*|zasad\w*|komend\w*|regu\w*)"

_PHRASES: tuple[str, ...] = (
    # "ignore previous instructions", "disregard all prior (instructions)"
    rf"\b(?:ignore|disregard|forget|override|bypass)\s+(?:all\s+(?:of\s+)?(?:the\s+|your\s+)?"
    rf"{_EARLIER_EN}\b|(?:any\s+|the\s+|your\s+)?{_EARLIER_EN}\s+{_ORDERS_EN}\b)",
    rf"\b(?:ignore|disregard|forget)\s+(?:all\s+|any\s+)?(?:your|the)\s+"
    rf"(?:system\s+prompt|{_ORDERS_EN})\s+(?:and|above|so\s+far)\b",
    # "you are now DAN / an unrestricted AI", "you are no longer bound by"
    r"\byou\s+are\s+now\s+(?:an?\s+)?(?:unrestricted|unfiltered|jailbroken|DAN\b|"
    r"(?:different|new)\s+(?:ai|assistant|model|agent)\b)",
    r"\byou\s+are\s+no\s+longer\s+(?:bound|restricted|limited|an?\s+(?:ai|assistant)\b)",
    r"\b(?:reveal|print|show|output|repeat|leak)\s+(?:me\s+)?(?:your|the)\s+"
    r"(?:system\s+prompt|initial\s+instructions|hidden\s+instructions)",
    r"\b(?:do\s+not|don't|never)\s+(?:tell|inform|mention\s+(?:this\s+)?to)\s+the\s+user\b",
    # Chat-template and system-prompt markers.
    r"<\|(?:im_start|im_end|system|endoftext)\|>|<<\s*/?SYS\s*>>|\[/?INST\]",
    r"^\s*#{0,6}\s*(?:new\s+)?system\s+(?:prompt|instructions?)\s*:",
    r"</?system(?:[-_]prompt)?>",
    # Polish equivalents of the English phrases above.
    rf"\b(?:zignoruj|ignoruj|pomi[n\u0144]|pomijaj|zapomnij(?:\s+o)?|nie\s+zwa[z\u017c]aj\s+na)"
    rf"\s+(?:wszystk\w*\s+|wszelk\w*\s+)?{_EARLIER_PL}\s+{_ORDERS_PL}",
    r"\bjeste[s\u015b]\s+teraz\s+(?:nieograniczon\w*|DAN\b|(?:innym|nowym)\s+"
    r"(?:asystentem|modelem|agentem))",
    r"\b(?:nie\s+m[o\u00f3]w|nie\s+informuj|nie\s+wspominaj)\s+(?:o\s+tym\s+)?"
    r"u[z\u017c]ytkownik\w*",
    r"\b(?:ujawnij|poka[z\u017c]|wypisz)\s+(?:sw[o\u00f3]j\s+|tw[o\u00f3]j\s+)?"
    r"(?:prompt\s+systemowy|instrukcje\s+systemowe)",
)
# One alternation, one pass over the text. Matches do not overlap, so a span
# two phrases would both cover is reported once.
_PATTERN = re.compile("|".join(f"(?:{p})" for p in _PHRASES), re.IGNORECASE | re.MULTILINE)


def _phrase(text: str) -> str:
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= _PHRASE_CHARS else collapsed[: _PHRASE_CHARS - 3] + "..."


def scan_text(path: str, text: str, *, with_lines: bool = True) -> list[Finding]:
    """Warnings for phrases that read like instructions to an AI agent."""
    # finditer yields in text order, so the report needs no sort.
    hits = [(m.start(), m.group(0)) for m in _PATTERN.finditer(text)]
    if not hits:
        return []
    offsets = _newline_offsets(text) if with_lines else []
    return [
        Finding(
            "warn",
            RULE,
            path,
            _line_at(offsets, pos) if with_lines else None,
            params={"phrase": _phrase(match)},
        )
        for pos, match in hits[:MAX_FINDINGS_PER_FILE]
    ]


def is_markdown_kind(kind: str) -> bool:
    return kind in ("md_single", "md_collection")


async def scan_markdown_asset(
    asset: Asset, settings: Settings, *, sources: MarkdownSources | None = None
) -> ScanReport:
    """Scan every Markdown file of the asset's current version. `sources`
    (from `read_markdown_files`) saves a second read when the caller already
    has the files at hand."""
    if sources is None:
        sources = await read_markdown_files(asset, settings)

    def _scan_all() -> list[Finding]:
        return [f for rel, text in sources for f in scan_text(rel, text)]

    return report_of(await asyncio.to_thread(_scan_all))


def apply_markdown_report(asset: Asset, report: ScanReport) -> dict:
    """Store the result on a Markdown asset. A clean result leaves no report."""
    asset.security_status = report.status
    asset.security_report = report.to_dict() if report.findings else None
    return {
        "status": report.status,
        "critical_count": 0,
        "warn_count": len(report.findings),
        "external_hosts": [],
    }
