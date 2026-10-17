"""Application code is English (ADR-0009, ADR-0011).

Comments, docstrings and string literals under `app/` contain no Polish.
User-facing text lives in the `app/i18n/*.json` catalogue, which is not
Python and so is not scanned here.
"""

from __future__ import annotations

import ast
import re
import tokenize
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
POLISH = re.compile(r"[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]")

# Docstrings that document Polish input on purpose.
ALLOWED_DOCSTRINGS = {
    ("routes/mcp_assets/search.py", "_build_tsquery"),
}

_DOC_OWNERS = ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef


def _comment_hits(path: Path) -> list[str]:
    hits = []
    with path.open("rb") as fh:
        for tok in tokenize.tokenize(fh.readline):
            if tok.type == tokenize.COMMENT and POLISH.search(tok.string):
                hits.append(f"{tok.start[0]}: {tok.string.strip()}")
    return hits


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """ids of the Constant nodes that are docstrings."""
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, _DOC_OWNERS) and node.body:
            first = node.body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                ids.add(id(first.value))
    return ids


def _docstring_hits(path: Path, rel: str) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, _DOC_OWNERS):
            continue
        doc = ast.get_docstring(node, clean=False)
        name = getattr(node, "name", "<module>")
        if doc and POLISH.search(doc) and (rel, name) not in ALLOWED_DOCSTRINGS:
            hits.append(f"docstring of {name}")
    return hits


def _literal_hits(path: Path) -> list[str]:
    """String literals (f-string parts included) outside docstrings; those
    are checked by `_docstring_hits` with its allowlist."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = _docstring_nodes(tree)
    return [
        f"{node.lineno}: {node.value[:60]!r}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
        and POLISH.search(node.value)
    ]


def test_app_comments_and_docstrings_are_english():
    problems = []
    for path in sorted(APP.rglob("*.py")):
        rel = path.relative_to(APP).as_posix()
        for hit in _comment_hits(path) + _docstring_hits(path, rel):
            problems.append(f"{rel}:{hit}")
    assert not problems, "\n".join(problems)


def test_app_string_literals_have_no_polish():
    """User-facing text goes through `app.i18n.t`; a Polish literal in code
    is a translation that bypassed the catalogue."""
    problems = []
    for path in sorted(APP.rglob("*.py")):
        rel = path.relative_to(APP).as_posix()
        problems += [f"{rel}:{hit}" for hit in _literal_hits(path)]
    assert not problems, "\n".join(problems)


def test_detector_catches_a_polish_comment(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text("x = 1  # zażółć\n", encoding="utf-8")
    assert _comment_hits(sample)


def test_comment_detector_ignores_string_literals(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text('MSG = "Brak dostępu"\n', encoding="utf-8")
    assert not _comment_hits(sample)
    assert not _docstring_hits(sample, "sample.py")


def test_literal_detector_catches_plain_and_f_strings(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text(
        'MSG = "Brak dostępu"\ndef f(n):\n    return f"{n} plików"\n', encoding="utf-8"
    )
    assert len(_literal_hits(sample)) == 2


def test_literal_detector_skips_docstrings(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text('"""Zażółć."""\ndef f():\n    """Gęślą."""\n', encoding="utf-8")
    assert not _literal_hits(sample)
