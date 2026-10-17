"""Every audit action written by the app must be registered in `AuditAction`.

The admin audit filter lists `AUDIT_ACTIONS`, so an unregistered action is
written but can never be filtered for. The static guard walks the source of
`app/` and checks every action handed to the audit writers; the integration
tests cover the two MCP lifecycle endpoints.
"""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from app.constants import AUDIT_ACTIONS
from app.models import AuditLog
from tests.conftest import login_as, mk_asset, mk_user

APP_DIR = Path(__file__).resolve().parent.parent / "app"

# Callee (as written at the call site) -> keyword that carries the action.
# The app imports the writer as `from app import audit`; inside `app/audit.py`
# it calls `record` and builds `AuditLog` directly.
AUDIT_WRITERS = {
    "audit.record": "action",
    "audit.record_from_request": "action",
    "record": "action",
    "AuditLog": "action",
    "commit_new_version": "audit_action",
    "asset_versions.commit_new_version": "audit_action",
}


def _callee_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return f"{func.value.id}.{func.attr}"
    if isinstance(func, ast.Name):
        return func.id
    return None


def _param_names(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    args = fn.args
    return {a.arg for a in [*args.posonlyargs, *args.args, *args.kwonlyargs]}


def _literal_actions(node: ast.expr, forwarded: set[str]) -> list[str] | None:
    """String literals the expression can evaluate to; `[]` for a parameter
    forwarded from the enclosing function (checked at its own call sites);
    `None` when the value cannot be resolved statically."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.IfExp):
        body = _literal_actions(node.body, forwarded)
        orelse = _literal_actions(node.orelse, forwarded)
        if body is None or orelse is None:
            return None
        return body + orelse
    if isinstance(node, ast.Name) and node.id in forwarded:
        return []
    return None


def _collect() -> tuple[list[tuple[str, int, str]], list[tuple[str, int]]]:
    actions: list[tuple[str, int, str]] = []
    unresolved: list[tuple[str, int]] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel = str(path.relative_to(APP_DIR.parent))
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            forwarded = _param_names(fn)
            for call in ast.walk(fn):
                if not isinstance(call, ast.Call):
                    continue
                callee = _callee_name(call) or ""
                if callee == "record" and path.name != "audit.py":
                    continue
                keyword = AUDIT_WRITERS.get(callee)
                if keyword is None:
                    continue
                for kw in call.keywords:
                    if kw.arg != keyword:
                        continue
                    values = _literal_actions(kw.value, forwarded)
                    if values is None:
                        unresolved.append((rel, call.lineno))
                    else:
                        actions.extend((rel, call.lineno, v) for v in values)
    return actions, unresolved


def test_every_written_audit_action_is_registered():
    actions, unresolved = _collect()
    # Sanity: the scan must actually see the writers, or it guards nothing.
    assert len(actions) > 50
    assert not unresolved, f"audit action is not a string literal: {unresolved}"
    missing = sorted({(f, line, a) for f, line, a in actions if a not in AUDIT_ACTIONS})
    assert not missing, f"audit actions missing from AuditAction: {missing}"


@pytest.mark.asyncio
async def test_undelete_and_set_tags_write_registered_actions(client, session, monkeypatch):
    async def _no_enqueue(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.routes.mcp_assets.lifecycle.enqueue", _no_enqueue)
    user = await mk_user(session)
    asset = await mk_asset(session, user)
    asset.deleted_at = datetime.now(UTC)
    await session.commit()
    await login_as(client, user)

    r = await client.post(f"/api/assets/{asset.id}/undelete")
    assert r.status_code == 200, r.text
    r = await client.put(f"/api/assets/{asset.id}/tags", json={"tags": ["alpha"]})
    assert r.status_code == 200, r.text

    rows = (
        await session.scalars(select(AuditLog.action).where(AuditLog.target == f"asset:{asset.id}"))
    ).all()
    assert set(rows) == {"asset_undeleted", "asset_tags_set"}
    assert all(a in AUDIT_ACTIONS for a in rows)


def test_every_action_has_a_label_in_the_admin_log():
    """The audit log shows each action by name (`auditAction.<code>` in the
    frontend catalogues); without one the admin sees the raw code."""
    locales = APP_DIR.parent.parent / "frontend" / "src" / "locales"
    for name in ("pl.json", "en.json"):
        catalogue = json.loads((locales / name).read_text(encoding="utf-8"))
        missing = [a for a in AUDIT_ACTIONS if f"auditAction.{a}" not in catalogue]
        assert missing == [], f"{name}: {missing}"
