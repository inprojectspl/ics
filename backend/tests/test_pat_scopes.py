"""Read-only token scope (ADR-0020): a PAT with `ics:read` gets 403
`insufficient_scope` on every writing route, the gate covers every writing
route of the app, and OAuth tokens of ics-mcp (`ics`) keep writing."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.routing import iter_route_contexts

from app.auth import enforce_token_scope
from app.config import get_settings
from app.main import create_app
from app.oauth import tokens as tokens_mod
from app.services import pat
from tests.conftest import mk_admin

READ = {"GET", "HEAD", "OPTIONS"}
_PARAM = re.compile(r"\{(\w+)(?::(\w+))?\}")


def _write_routes() -> list[tuple[str, str, object]]:
    out = []
    for route in iter_route_contexts(create_app().routes):
        methods = set(getattr(route, "methods", None) or ()) - READ
        for method in sorted(methods):
            out.append((method, route.path, route.dependant))
    return out


WRITE_ROUTES = _write_routes()


def _concrete(path: str) -> str:
    def fill(m: re.Match) -> str:
        name, conv = m.group(1), m.group(2)
        if conv == "path":
            return "doc.md"
        if name == "id" or name.endswith("_id"):
            return str(uuid4())
        if conv == "int" or name.endswith(("_v", "version")):
            return "1"
        return "some-slug"

    return _PARAM.sub(fill, path)


def _depends_on(dependant, target) -> bool:
    return any(d.call is target or _depends_on(d, target) for d in dependant.dependencies)


def test_every_writing_route_has_the_scope_gate():
    assert len(WRITE_ROUTES) > 50
    missing = [
        f"{m} {p}" for m, p, dep in WRITE_ROUTES if not _depends_on(dep, enforce_token_scope)
    ]
    assert missing == []


@pytest.fixture
async def read_token(session) -> str:
    # An admin: the gate must hold even for the strongest account.
    user = await mk_admin(session)
    _, plaintext = await pat.create(
        session, user=user, name="ps", expires_at=datetime.now(UTC) + timedelta(days=30)
    )
    await session.commit()
    return plaintext


@pytest.mark.parametrize(
    ("method", "path"), [(m, p) for m, p, _ in WRITE_ROUTES], ids=lambda v: str(v)
)
async def test_read_only_pat_cannot_write(client, read_token, method, path):
    r = await client.request(
        method, _concrete(path), headers={"Authorization": f"Bearer {read_token}"}
    )
    assert r.status_code == 403, (method, path, r.status_code, r.text[:200])
    assert r.json()["code"] == "insufficient_scope"


async def test_read_only_pat_still_reads(client, read_token):
    r = await client.get("/api/assets", headers={"Authorization": f"Bearer {read_token}"})
    assert r.status_code == 200


async def test_invalid_pat_on_a_writing_route_is_still_a_bearer_401(client):
    r = await client.post("/api/assets", headers={"Authorization": "Bearer ics_pat_deadbeef_nope"})
    assert r.status_code == 401
    assert "www-authenticate" in r.headers


async def test_oauth_bearer_token_still_writes(client, session, monkeypatch, fs_storage):
    settings = get_settings()
    audience = "https://ics-test.example/mcp"
    monkeypatch.setattr(settings, "mcp_resource_uri", audience)
    user = await mk_admin(session)
    await session.commit()
    token, _jti = tokens_mod.sign_access_jwt(
        settings=settings,
        user=user,
        client_id_external="ics-mcp-stdio",
        scopes=["ics"],
        audience=audience,
    )

    r = await client.post(
        "/api/assets",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("note.md", b"# Note\n", "text/markdown")},
    )
    assert r.status_code == 201, r.text
