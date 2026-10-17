"""API error contract: English `detail`, a stable documented `code` (ADR-0009).

The static checks walk the AST of `app/`, so a new error that skips
`ApiError`, carries Polish text or an undocumented code fails here.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from app.errors import ApiError, error_code
from app.slug import generate_slug

BACKEND = Path(__file__).resolve().parent.parent
APP = BACKEND / "app"
DOCS = BACKEND.parent / "docs" / "api-errors.md"
POLISH = re.compile(r"[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]")
CODE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _calls(name: str) -> list[tuple[str, ast.Call]]:
    found = []
    for path in sorted(APP.rglob("*.py")):
        rel = path.relative_to(APP).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            called = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if called == name:
                found.append((f"{rel}:{node.lineno}", node))
    return found


def _strings(node: ast.AST) -> list[str]:
    return [
        n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]


# Domain errors take `(code, detail)`; `app.errors` maps them to a status.
_DOMAIN_ERRORS = (
    "InvalidInputError",
    "AccessDeniedError",
    "NotFoundError",
    "ConflictError",
    "LimitExceededError",
    "QuotaExceededError",
)


def _error_calls() -> list[tuple[str, ast.expr | None, list[ast.expr]]]:
    """`(where, code argument, detail arguments)` of every ApiError and
    domain error raised in `app/`."""
    found = []
    for where, call in _calls("ApiError"):
        code = call.args[1] if len(call.args) > 1 else None
        found.append((where, code, call.args[2:] + [k.value for k in call.keywords]))
    for name in _DOMAIN_ERRORS:
        for where, call in _calls(name):
            code = call.args[0] if call.args else None
            found.append((where, code, call.args[1:] + [k.value for k in call.keywords]))
    return found


def _documented_codes() -> set[str]:
    return set(re.findall(r"^\| `([a-z0-9_]+)` \|", DOCS.read_text(encoding="utf-8"), re.M))


def test_http_exception_is_not_constructed_directly():
    offenders = [where for where, _ in _calls("HTTPException") if not where.startswith("errors.py")]
    assert not offenders, "raise app.errors.ApiError instead:\n" + "\n".join(offenders)


def test_api_error_details_are_english():
    offenders = []
    for where, _code, details in _error_calls():
        for arg in details:
            offenders += [f"{where}: {s!r}" for s in _strings(arg) if POLISH.search(s)]
    assert not offenders, "\n".join(offenders)


def test_api_error_codes_are_literal_and_documented():
    documented = _documented_codes()
    problems = []
    for where, code, _details in _error_calls():
        if not isinstance(code, ast.Constant):
            # Codes picked from a mapping; the mapping's literals are
            # covered by the docs check below.
            continue
        if not CODE_RE.match(code.value):
            problems.append(f"{where}: malformed code {code.value!r}")
        elif code.value not in documented:
            problems.append(f"{where}: {code.value!r} missing from docs/api-errors.md")
    assert not problems, "\n".join(problems)


def test_mapped_codes_are_documented():
    from app.routes.shares._shared import _GONE_ERROR

    documented = _documented_codes()
    assert {code for code, _ in _GONE_ERROR.values()} <= documented


def test_detector_catches_polish_detail(tmp_path):
    tree = ast.parse('ApiError(400, "x", "brak dostępu")')
    call = tree.body[0].value
    assert any(POLISH.search(s) for s in _strings(call.args[2]))


def test_error_code_falls_back_to_status():
    from starlette.exceptions import HTTPException

    assert error_code(ApiError(404, "asset_not_found", "asset not found")) == "asset_not_found"
    assert error_code(HTTPException(404)) == "not_found"
    assert error_code(HTTPException(418)) == "http_error"
    assert error_code(HTTPException(502)) == "server_error"


@pytest.mark.asyncio
async def test_error_response_carries_code_and_no_store(client):
    email = f"nobody-{generate_slug()}@example.com"
    r = await client.post("/api/auth/login", json={"email": email, "password": "Whatever1!"})
    assert r.status_code == 401
    assert r.json()["code"] == "invalid_credentials"
    assert "no-store" in r.headers["cache-control"]


@pytest.mark.asyncio
async def test_unknown_route_gets_generic_code(client):
    r = await client.get("/api/no-such-route")
    assert r.status_code == 404
    assert r.json()["code"] == "not_found"


@pytest.mark.asyncio
async def test_validation_error_keeps_detail_list(client):
    r = await client.post("/api/auth/login", json={})
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "validation_error"
    assert isinstance(body["detail"], list)


@pytest.mark.asyncio
async def test_domain_errors_map_to_their_category_status():
    from app.domain_errors import (
        AccessDeniedError,
        ConflictError,
        InvalidInputError,
        LimitExceededError,
        NotFoundError,
    )
    from app.errors import domain_error_handler
    from app.quota import QuotaExceededError

    cases = {
        InvalidInputError: 400,
        AccessDeniedError: 403,
        NotFoundError: 404,
        ConflictError: 409,
        LimitExceededError: 413,
        QuotaExceededError: 413,
    }
    for cls, status_code in cases.items():
        r = await domain_error_handler(None, cls("some_code", "some detail"))  # type: ignore[arg-type]
        assert r.status_code == status_code
        assert json.loads(bytes(r.body)) == {"detail": "some detail", "code": "some_code"}
        assert "no-store" in r.headers["cache-control"]
