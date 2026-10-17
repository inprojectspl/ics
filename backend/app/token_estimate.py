"""Token estimates ICS reports to agents, calibrated against cl100k.

Prose: ~4 chars/token, ~2.7 for accented (Polish) text, picked by the share of
multi-byte characters; migration 0041 repeats this rule in SQL, keep them in step.
JSON packs get `tokens_for_json`, since ids and punctuation tokenise far denser.
"""

from __future__ import annotations

import math
import re
from typing import Any

import orjson

CHARS_PER_TOKEN = 4.0
CHARS_PER_TOKEN_ACCENTED = 2.7
# Extra UTF-8 bytes per character from which text counts as accented.
ACCENTED_SHARE = 0.01
# JSON: identifiers (slugs, UUIDs, timestamps) and the punctuation around values.
CHARS_PER_TOKEN_ID = 1.5
CHARS_PER_TOKEN_PUNCT = 4.0
CHARS_PER_TOKEN_NUMBER = 3.0
_IDENTIFIER = re.compile(r"[A-Za-z0-9_\-:/.#]{6,}")


def tokens_for_chars(chars: int, *, accented: bool = False) -> int:
    """Tokens for a text of `chars` characters when only its length is known."""
    return math.ceil(chars / (CHARS_PER_TOKEN_ACCENTED if accented else CHARS_PER_TOKEN))


def tokens_for_text(text: str) -> int:
    chars = len(text)
    if not chars:
        return 0
    extra_bytes = len(text.encode("utf-8")) - chars
    return tokens_for_chars(chars, accented=extra_bytes >= ACCENTED_SHARE * chars)


def _string_tokens(text: str) -> int:
    if _IDENTIFIER.fullmatch(text) and any(ch.isdigit() for ch in text):
        return math.ceil(len(text) / CHARS_PER_TOKEN_ID)
    return tokens_for_text(text)


def tokens_for_json(value: Any) -> int:
    """Tokens of `value` serialised as compact JSON: every string (keys
    included) by its own rule, numbers in 3-digit groups, `true`/`false`/
    `null` one token each, and the remaining punctuation by its length."""
    content = 0
    tokens = 0
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key, child in item.items():
                content += len(key)
                tokens += _string_tokens(key)
                stack.append(child)
        elif isinstance(item, list | tuple):
            stack.extend(item)
        elif isinstance(item, str):
            content += len(item)
            tokens += _string_tokens(item)
        elif item is None or isinstance(item, bool):
            content += 5 if item is False else 4
            tokens += 1
        else:
            digits = len(orjson.dumps(item))
            content += digits
            tokens += math.ceil(digits / CHARS_PER_TOKEN_NUMBER)
    punctuation = len(orjson.dumps(value).decode("utf-8")) - content
    return tokens + math.ceil(max(punctuation, 0) / CHARS_PER_TOKEN_PUNCT)
