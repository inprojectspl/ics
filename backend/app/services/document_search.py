"""One query language and ranking for browser and MCP document discovery."""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

from sqlalchemy import ColumnElement, Text, and_, case, cast, false, func, literal, or_
from sqlalchemy.dialects.postgresql import REGCONFIG, TSQUERY

from app.models import Asset, User
from app.services import graph_signals

SearchMatch = Literal["all", "any"]
SEARCH_CONFIG = cast(literal("public.ics_search"), REGCONFIG)

# Keep identifiers such as v1.3, file.md and project-standard intact so the
# PostgreSQL parser tokenizes them exactly as it tokenizes the document.
_TERM = re.compile(r"[^\W_]+(?:[./@-][^\W_]+)*", re.UNICODE)
_PART = re.compile(r'"([^\"]*)"|([^\"]+)', re.UNICODE)
_START = r"(?<![[:alnum:]])(?<![[:alnum:]][./@-])"
_END = r"(?![[:alnum:]]|[./@-][[:alnum:]])"


def _clauses(q: str) -> list[tuple[str, str | None]]:
    clauses: list[tuple[str, str | None]] = []
    for part in _PART.finditer(unicodedata.normalize("NFC", q)):
        phrase, words = part.groups()
        if phrase is not None:
            terms = _TERM.findall(phrase)
            if terms:
                # A non-positional GIN prefilter avoids tsvector's position
                # limits (16,383 tokens and 256 positions per lexeme).
                query = "(" + " & ".join(f"'{t}'" for t in terms) + ")"
                # Do not mistake v1.3.1 for v1.3 or enter prefix.alpha
                # halfway through an identifier preserved by _TERM.
                pattern = _START + "[^[:alnum:]]+".join(re.escape(t) for t in terms) + _END
                clauses.append((query, pattern))
        else:
            for term in _TERM.findall(words):
                if len(term) >= 2:
                    # PostgreSQL splits some identifiers (dates, URLs) into
                    # several lexemes. They must still belong to one field,
                    # with the literal identifier prefix intact.
                    prefix_pattern = (
                        _START + re.escape(term) if re.search(r"[./@-]", term) else None
                    )
                    clauses.append((f"'{term}':*", prefix_pattern))
                elif term.isdigit():
                    clauses.append((f"'{term}'", None))
    return list(dict.fromkeys(clauses))


def build_tsquery(q: str, match: SearchMatch = "all") -> str | None:
    """Safe, indexable candidates. Phrases and identifiers are verified per field.

    Input is API-bounded, never silently cut to the first N words.
    Bare words match prefixes; single letters are ignored, digits exact.
    Only parser-produced terms enter tsquery syntax, never raw user input.
    """
    return (" | " if match == "any" else " & ").join(c[0] for c in _clauses(q)) or None


def _candidate_query(query: str):
    # to_tsquery also inserts adjacency for hyphenated words, dates and
    # URLs. Remove it from candidates, which must survive position limits;
    # the original identifier/phrase is verified against the full field.
    parsed = cast(func.to_tsquery(SEARCH_CONFIG, query), Text)
    return cast(func.replace(parsed, "<->", "&"), TSQUERY)


def query_expression(q: str, match: SearchMatch = "all"):
    return _candidate_query(build_tsquery(q, match) or "")


def _match(vector, fields: list, q: str, match: SearchMatch):
    clauses = _clauses(q)
    if not clauses:
        return false()
    candidate = vector.bool_op("@@")(query_expression(q, match))
    verifications = [(query, pattern) for query, pattern in clauses if pattern is not None]
    if not verifications:
        return candidate

    def field_match(pattern: str):
        # Verification sees the full original field, so it cannot cross
        # metadata boundaries or lose late/repeated phrase occurrences.
        return or_(
            *(func.unaccent(field).bool_op("~*")(func.unaccent(pattern)) for field in fields)
        )

    if match == "all":
        return and_(candidate, *(field_match(pattern) for _, pattern in verifications))
    alternatives = [
        and_(vector.bool_op("@@")(_candidate_query(query)), field_match(pattern))
        for query, pattern in verifications
    ]
    bare = " | ".join(query for query, pattern in clauses if pattern is None)
    if bare:
        alternatives.append(vector.bool_op("@@")(_candidate_query(bare)))
    return and_(candidate, or_(*alternatives))


def search_filter(q: str, match: SearchMatch = "all") -> ColumnElement[bool]:
    return _match(
        Asset.search_tsv,
        [
            Asset.title,
            Asset.slug,
            Asset.summary,
            func.ics_immutable_array_to_string(Asset.tags, " "),
            Asset.search_content,
        ],
        q,
        match,
    )


def search_score(q: str, user: User, match: SearchMatch = "all"):
    """Exact titles, then title matches, then weighted text relevance.

    Normalization 32 bounds the text rank below one, so repetition in a
    long body cannot displace a matching title. Only visible successors
    affect freshness. Stable tie breakers are applied by the caller.
    """
    query = query_expression(q, match)
    title = func.coalesce(Asset.title, Asset.slug)
    exact_title = func.lower(func.unaccent(title)) == func.lower(
        func.unaccent(q.strip().strip('"'))
    )
    title_match = _match(func.to_tsvector(SEARCH_CONFIG, title), [title], q, match)
    rank = case((exact_title, 2.0), (title_match, 1.0), else_=0.0) + func.ts_rank_cd(
        Asset.search_tsv, query, 32
    )
    return rank * graph_signals.rank_factor(user, Asset.id.__clause_element__())


def relevance_order(q: str, user: User, match: SearchMatch = "all") -> list:
    return [
        search_score(q, user, match).desc(),
        func.coalesce(Asset.content_updated_at, Asset.updated_at).desc(),
        Asset.id.asc(),
    ]
