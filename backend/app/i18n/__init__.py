"""Message catalogue for user-facing text the backend renders (ADR-0011).

API error `detail` stays English; clients translate by `code`. Placeholders
use a regex, not `str.format`, so a catalogue value cannot reach attributes
or indexes of a parameter.
"""

from __future__ import annotations

import html
import json
import logging
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Final, Literal, get_args

logger = logging.getLogger("ics.i18n")

Locale = Literal["en", "pl"]
SUPPORTED_LOCALES: Final[tuple[Locale, ...]] = get_args(Locale)
DEFAULT_LOCALE: Final[Locale] = "en"

_DIR = Path(__file__).resolve().parent
_PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


def _load(locale: Locale) -> dict[str, str]:
    data = json.loads((_DIR / f"{locale}.json").read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not all(isinstance(v, str) for v in data.values()):
        raise RuntimeError(f"i18n: {locale}.json must be a flat object of strings")
    return data


CATALOGUES: Final[dict[Locale, dict[str, str]]] = {loc: _load(loc) for loc in SUPPORTED_LOCALES}


class SafeHtml(str):
    """A parameter that `t_html` inserts without escaping (markup built by
    the caller from already escaped parts)."""

    __slots__ = ()


def strong(value: str) -> SafeHtml:
    """`value` escaped and in bold, for a `t_html` parameter."""
    return SafeHtml(f"<strong>{html.escape(value)}</strong>")


def has_key(key: str) -> bool:
    """Whether `key` exists (in English, the fallback of every locale)."""
    return key in CATALOGUES[DEFAULT_LOCALE]


def template_has_params(key: str) -> bool:
    """Whether the English text of `key` has `{name}` placeholders."""
    return _PLACEHOLDER.search(CATALOGUES[DEFAULT_LOCALE].get(key, "")) is not None


def _template(key: str, locale: str | None) -> str:
    loc = normalize_locale(locale) or DEFAULT_LOCALE
    value = CATALOGUES[loc].get(key)
    if value is None:
        value = CATALOGUES[DEFAULT_LOCALE].get(key)
    if value is None:
        # A missing key is a bug, but a mail or a page must still go out.
        logger.warning("i18n: missing key %r", key)
        return key
    return value


def _interpolate(template: str, params: Mapping[str, str]) -> str:
    def repl(m: re.Match[str]) -> str:
        name = m.group(1)
        if name not in params:
            logger.warning("i18n: missing parameter %r", name)
            return m.group(0)
        return params[name]

    return _PLACEHOLDER.sub(repl, template)


def t(key: str, locale: str | None, **params: object) -> str:
    """Plain-text message for `key` in `locale`, English when the locale or
    the key is unknown."""
    return _interpolate(_template(key, locale), {k: str(v) for k, v in params.items()})


def t_html(key: str, locale: str | None, **params: object) -> str:
    """Like `t`, but HTML-escaped: the catalogue text and every parameter
    are escaped, except parameters wrapped in `SafeHtml`."""
    escaped = {k: v if isinstance(v, SafeHtml) else html.escape(str(v)) for k, v in params.items()}
    return _interpolate(html.escape(_template(key, locale)), escaped)


def plural_category(n: int, locale: str | None) -> Literal["one", "few", "many"]:
    """CLDR-style plural category, reduced to the forms the catalogue uses.

    English has one and many; Polish adds few (2-4, except 12-14).
    """
    if n == 1:
        return "one"
    if normalize_locale(locale) == "pl" and 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "few"
    return "many"


def tn(key: str, n: int, locale: str | None, **params: object) -> str:
    """Plural form: looks up `key.one`, `key.few` or `key.many`, with `n` as
    the `{n}` parameter."""
    return t(f"{key}.{plural_category(n, locale)}", locale, n=n, **params)


def normalize_locale(value: str | None) -> Locale | None:
    """`"pl-PL"` -> `"pl"`; `None` for anything unsupported."""
    if not value:
        return None
    primary = value.strip().split("-", 1)[0].split("_", 1)[0].lower()
    return next((loc for loc in SUPPORTED_LOCALES if loc == primary), None)


def negotiate(accept_language: str | None) -> Locale | None:
    """Best supported locale from an `Accept-Language` header, by q-value
    and then by order. `None` when nothing matches."""
    if not accept_language:
        return None
    ranked: list[tuple[float, int, Locale]] = []
    for idx, part in enumerate(accept_language.split(",")):
        tag, _, rest = part.strip().partition(";")
        q = 1.0
        for attr in rest.split(";"):
            name, _, val = attr.strip().partition("=")
            if name.strip().lower() == "q":
                try:
                    q = float(val)
                except ValueError:
                    q = 0.0
        loc = normalize_locale(tag)
        if loc is not None and q > 0:
            ranked.append((-q, idx, loc))
    return min(ranked)[2] if ranked else None


def resolve_locale(*preferred: str | None, accept_language: str | None = None) -> Locale:
    """First supported locale among `preferred` (e.g. the recipient's, then
    the sender's stored locale), then the request's `Accept-Language`, then
    English."""
    for value in preferred:
        loc = normalize_locale(value)
        if loc is not None:
            return loc
    return negotiate(accept_language) or DEFAULT_LOCALE


__all__ = [
    "CATALOGUES",
    "DEFAULT_LOCALE",
    "SUPPORTED_LOCALES",
    "Locale",
    "SafeHtml",
    "has_key",
    "negotiate",
    "normalize_locale",
    "plural_category",
    "resolve_locale",
    "strong",
    "t",
    "t_html",
    "template_has_params",
    "tn",
]
