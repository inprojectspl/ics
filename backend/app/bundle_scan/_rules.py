"""Rule definitions for Layer 2 static analysis; severity is decided by
`severity_for`.

A finding stores a message `code` plus `params`, rendered per reader locale
from the `scan.<code>` catalogue key (ADR-0011): a new rule needs that key
in every locale file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

Severity = Literal["info", "warn", "critical"]
Status = Literal["clean", "warn", "critical"]
Policy = Literal["permissive", "strict"]


@dataclass
class Finding:
    severity: Severity
    rule: str
    file: str
    line: int | None
    params: dict[str, str] = field(default_factory=dict)
    # Catalogue code of the message (`scan.<code>`); defaults to the rule.
    code: str = ""

    def __post_init__(self) -> None:
        if not self.code:
            self.code = self.rule


@dataclass(frozen=True)
class Rule:
    """Regex-based scan rule.

    `category`: "html" searches HTML files; "js" searches JS files and
    inline `<script>` blocks inside HTML.
    """

    name: str
    pattern: re.Pattern[str]
    category: Literal["html", "js"]


# Inline event handler attributes (onclick=, onerror=, onload= ...).
_EVENT_HANDLER_RE = re.compile(r"""\son[a-z]+\s*=\s*['"]""", re.IGNORECASE)

# javascript: protocol in href/src.
_JS_PROTOCOL_RE = re.compile(
    r"""(?:href|src|action|formaction)\s*=\s*['"]\s*javascript:""",
    re.IGNORECASE,
)

# data: with HTML/script content (data:text/html, data:application/javascript).
_DATA_DANGEROUS_RE = re.compile(
    r"""(?:href|src)\s*=\s*['"]\s*data:(?:text/html|application/(?:javascript|x-javascript|ecmascript))""",
    re.IGNORECASE,
)

# JS: eval() / new Function() / setTimeout(string) / setInterval(string).
_EVAL_RE = re.compile(r"\beval\s*\(")
_NEW_FUNCTION_RE = re.compile(r"\bnew\s+Function\s*\(")
_DOCUMENT_WRITE_RE = re.compile(r"\bdocument\s*\.\s*write(ln)?\s*\(")
# setTimeout / setInterval with a string literal as first arg (vs function).
_TIMER_STRING_RE = re.compile(
    r"""\bset(?:Timeout|Interval)\s*\(\s*['"`]""",
    re.IGNORECASE,
)
# Direct fetch / XMLHttpRequest to private/loopback IPs.
_LOOPBACK_HOSTS_RE = re.compile(
    r"""['"]https?://(?:localhost|127\.0\.0\.1|10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.)""",
    re.IGNORECASE,
)
# Cookie access, read or write. Classic session-exfil signal that
# stays critical even in permissive mode.
_DOCUMENT_COOKIE_RE = re.compile(r"\bdocument\s*\.\s*cookie\b")

# `<meta http-equiv="refresh" content="0;url=...">`. Bundles uploaded by
# authenticated users can push a redirect to a phishing domain, so the
# scanner has to see that a "clean" bundle navigates cross-origin before
# the viewer does it.
_META_REFRESH_RE = re.compile(
    r"""<meta\b[^>]*\bhttp-equiv\s*=\s*['"]\s*refresh\s*['"][^>]*>""",
    re.IGNORECASE,
)

# An SVG-embedded `<script>` runs in the parent document. Separate open,
# close and inner patterns for the reason at INLINE_SCRIPT_OPEN_RE.
# `SVG_CLOSE_RE` allows a space before `>` like the HTML parser does, or
# `</svg ><script>` would flag a script outside the element.
SVG_OPEN_RE = re.compile(r"<svg\b[^>]*>", re.IGNORECASE)
SVG_CLOSE_RE = re.compile(r"</svg\s*>", re.IGNORECASE)
SVG_INNER_SCRIPT_RE = re.compile(r"<script\b", re.IGNORECASE)

SVG_SCRIPT_RULE = "svg_script"


# HTML-only rules: straight regex check, one match = one finding.
# external_script_src is separate (it needs host extraction and a
# trusted-host check), see scanner._scan_external_scripts.
HTML_RULES: tuple[Rule, ...] = (
    Rule("javascript_protocol", _JS_PROTOCOL_RE, "html"),
    Rule("data_url_active", _DATA_DANGEROUS_RE, "html"),
    Rule("inline_event_handler", _EVENT_HANDLER_RE, "html"),
    Rule("meta_refresh", _META_REFRESH_RE, "html"),
)
# `svg_script` is deliberately outside HTML_RULES: it is not a single
# regex, the scanner handles it through `_iter_svg_scripts`.

# JS rules: checked in JS files and in inline <script> blocks.
JS_RULES: tuple[Rule, ...] = (
    Rule("eval_call", _EVAL_RE, "js"),
    Rule("new_function", _NEW_FUNCTION_RE, "js"),
    Rule("document_write", _DOCUMENT_WRITE_RE, "js"),
    Rule("timer_string_arg", _TIMER_STRING_RE, "js"),
    Rule("loopback_fetch", _LOOPBACK_HOSTS_RE, "js"),
    Rule("document_cookie", _DOCUMENT_COOKIE_RE, "js"),
)

# External script regex kept separate: it needs a capture group to extract
# the host for the severity decision and the external_hosts report.
EXTERNAL_SCRIPT_RE = re.compile(
    r"""<script[^>]*\bsrc\s*=\s*['"](https?://[^'"]+)['"]""",
    re.IGNORECASE,
)

# `href` attribute values (quoted or bare), for link extraction from bundle
# pages (ADR-0016). No nested quantifier, so linear on minified HTML.
HREF_RE = re.compile(
    r"""<(?:a|area|link)\b[^>]*?\shref\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""",
    re.IGNORECASE,
)

# Inline <script> blocks (no src). Open and close tags are matched
# separately and the body sliced by index: a lazy alternation over the body
# keeps backtracking state per character, close to 1 GB RSS on multi-MB
# minified HTML.
INLINE_SCRIPT_OPEN_RE = re.compile(
    r"""<script(?![^>]*\bsrc=)[^>]*>""",
    re.IGNORECASE,
)
INLINE_SCRIPT_CLOSE_RE = re.compile(r"</script", re.IGNORECASE)


def severity_for(
    rule: str,
    *,
    policy: Policy,
    host: str | None = None,
    trusted_hosts: frozenset[str] | None = None,
) -> Severity:
    """Severity of a finding under `policy`. Soft signals common in
    legitimate AI-generated demos are downgraded in permissive mode."""
    if rule == "external_script_src":
        # In strict mode, every external script is critical regardless
        # of host: the allowlist is a permissive-mode relaxation, not
        # a global trust statement.
        if policy == "strict":
            return "critical"
        if host and trusted_hosts and host in trusted_hosts:
            return "info"
        return "warn"

    # Unambiguous signals; no legitimate demo needs an SVG-embedded script.
    if rule in {
        "eval_call",
        "new_function",
        "javascript_protocol",
        "data_url_active",
        "document_cookie",
        "svg_script",
    }:
        return "critical"

    # `meta_refresh` may be a self-reload, but cross-origin it is a classic
    # phishing redirect.
    if rule in {"inline_event_handler", "document_write", "meta_refresh"}:
        return "info" if policy == "permissive" else "warn"
    if rule in {"timer_string_arg", "loopback_fetch"}:
        return "warn"

    return "info"
