"""No source file exceeds the 500-line budget (ADR-0002, I1).

Covers `backend/app` and `frontend/src`, the same scope as the manual
`wc -l` check. Frontend files are skipped when the tree is not checked out
next to the backend (e.g. a backend-only CI image).
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
BUDGET = 500
SCOPES = (
    (ROOT / "backend" / "app", ("*.py",)),
    (ROOT / "frontend" / "src", ("*.ts", "*.tsx")),
)


def _line_count(path: Path) -> int:
    with path.open("rb") as fh:
        return sum(1 for _ in fh)


def _oversized() -> list[str]:
    hits = []
    for base, patterns in SCOPES:
        if not base.is_dir():
            continue
        for pattern in patterns:
            for path in base.rglob(pattern):
                if "node_modules" in path.parts:
                    continue
                lines = _line_count(path)
                if lines > BUDGET:
                    hits.append(f"{path.relative_to(ROOT)}: {lines}")
    return sorted(hits)


def test_source_files_stay_within_budget() -> None:
    if not (ROOT / "backend" / "app").is_dir():
        pytest.skip("backend sources not found")
    assert _oversized() == []
