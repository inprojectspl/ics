"""Micro-applications: manifest contract, plan/apply, the closed generic
routes, access rights, launch codes and the internal broker API.

Publication with real provisioning (schemas and roles in a separate
database) runs when ICS_MICROAPPS_TEST_PROVISIONER_URL points at a server
where that role may create a scratch `ics_apps_test_*` database (the local
profile provides it); otherwise those tests are skipped, not faked.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from urllib.parse import urlparse

import asyncpg
import pytest
from sqlalchemy import select

from app.config import get_settings
from app.domain_errors import InvalidInputError
from app.models import (
    Asset,
    AssetShare,
    AssetVersion,
    MicroAppCleanupOrder,
    MicroAppEnvironment,
    MicroAppGrant,
    MicroAppOperation,
    MicroAppPlan,
    MicroAppRelease,
    MicroAppSchemaBinding,
    Project,
    ProjectMember,
)
from app.oauth import tokens as tokens_mod
from app.services.micro_applications import access, ddl, manifest, provisioning, publish, runtime
from app.services.micro_applications.provisioning import Names
from app.slug import generate_slug
from app.storage import storage_from_url
from app.util import now as utc_now
from tests.conftest import login_as, mk_user

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples" / "microapps"
TEMPLATE = Path(manifest.__file__).with_name("template")
AUDIENCE = "https://ics-test.example/mcp"
SECRET = "SECRET-HANDLER-MARKER-7f3a"


def _files(root: Path) -> list[tuple[str, bytes]]:
    return [
        (p.relative_to(root).as_posix(), p.read_bytes())
        for p in sorted(root.rglob("*"))
        if p.is_file()
    ]


def _payload(root: Path) -> list[dict[str, str]]:
    return [{"path": p, "content_text": b.decode()} for p, b in _files(root)]


@pytest.fixture(autouse=True)
def _enabled(monkeypatch, tmp_path):
    s = get_settings()
    monkeypatch.setattr(s, "microapps_enabled", True)
    monkeypatch.setattr(s, "microapps_service_token", "svc-token-test")
    monkeypatch.setattr(s, "mcp_resource_uri", AUDIENCE)
    monkeypatch.setattr(s, "storage_url", f"fs://{tmp_path}")

    async def compile_ok(settings, method, path, body=None, timeout=15.0):
        if path == "/admin/compile":
            return {
                "results": {p: {"ok": "SYNTAX_ERROR" not in c} for p, c in body["files"].items()}
            }
        return {"drained": True, "inflight": 0}

    from app.services.micro_applications import common, control, plan

    monkeypatch.setattr(common, "broker_admin", compile_ok)
    monkeypatch.setattr(plan, "broker_admin", compile_ok)
    monkeypatch.setattr(publish, "broker_admin", compile_ok)
    monkeypatch.setattr(control, "broker_admin", compile_ok)

    async def no_enqueue(*a, **k):
        return None

    from app.jobs.tasks import micro_applications as jobs

    monkeypatch.setattr(jobs, "enqueue_operation", no_enqueue)
    monkeypatch.setattr(jobs, "enqueue_control_retry", no_enqueue)


def bearer(user) -> dict[str, str]:
    token, _ = tokens_mod.sign_access_jwt(
        settings=get_settings(),
        user=user,
        client_id_external="ics-mcp-stdio",
        scopes=["ics"],
        audience=AUDIENCE,
    )
    return {"Authorization": f"Bearer {token}"}


# ---------- contract ----------


@pytest.mark.parametrize(
    "root",
    [*sorted(p for p in EXAMPLES.iterdir() if p.is_dir()), TEMPLATE],
    ids=lambda p: p.name,
)
def test_example_packages_pass_the_contract(root):
    pkg = manifest.load_package(_files(root))
    assert pkg.ok, [d.as_dict() for d in pkg.diagnostics]


def _with_manifest(change) -> list[tuple[str, bytes]]:
    files = dict(_files(EXAMPLES / "requests"))
    m = json.loads(files["microapp.json"])
    change(m)
    files["microapp.json"] = json.dumps(m).encode()
    return list(files.items())


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (lambda m: m.update(apiVersion="ics.microapp/v9"), "manifest_schema"),
        (
            lambda m: m["database"]["collections"]["requests"]["fields"].update(
                id={"type": "uuid"}
            ),
            "field_reserved",
        ),
        (
            lambda m: m["permissions"].pop("requests.approve"),
            "permission_not_declared",
        ),
        (
            lambda m: m["endpoints"][1].update(capabilities=["requests.approve"]),
            "read_only_write_capability",
        ),
        (lambda m: m["endpoints"][0].update(method="GET"), "get_must_be_read_only"),
        (
            lambda m: m["database"]["collections"]["requests"]["crud"]["update"][
                "writeFields"
            ].append("revision"),
            "system_field_not_writable",
        ),
        (lambda m: m["limitsRequested"].update(wallMs=60000), "limit_above_platform"),
        (
            lambda m: m["endpoints"][0].update(handler="handlers/missing.mjs#default"),
            "handler_missing",
        ),
    ],
)
def test_contract_violations_have_stable_codes_and_pointers(change, code):
    pkg = manifest.load_package(_with_manifest(change))
    assert not pkg.ok
    assert code in {d.code for d in pkg.diagnostics}
    assert all(d.pointer is not None for d in pkg.diagnostics)


@pytest.mark.parametrize(
    ("change", "code", "pointer"),
    [
        (
            lambda m: m["roles"]["reviewer"]["permissions"].append("requests.fly"),
            "permission_not_declared",
            "/roles/reviewer/permissions/2",
        ),
        (
            lambda m: m["roles"]["reviewer"]["permissions"].append("app.publish"),
            "permission_not_declared",
            "/roles/reviewer/permissions/2",
        ),
        (
            lambda m: m["permissions"].update({"app.fly": {"label": "Fly"}}),
            "permission_reserved",
            "/permissions/app.fly",
        ),
        (
            lambda m: m["roles"]["reviewer"].update(permissions=["requests.read"]),
            "permission_without_role",
            "/permissions/requests.approve",
        ),
        (lambda m: m.pop("roles"), "manifest_schema", None),
        (lambda m: m["permissions"]["requests.read"].pop("label"), "manifest_schema", None),
        (lambda m: m["roles"].update({"Boss": m["roles"]["reviewer"]}), "manifest_schema", None),
        (lambda m: m["roles"]["reviewer"].update(permissions=[]), "manifest_schema", None),
    ],
)
def test_roles_name_only_declared_permissions(change, code, pointer):
    pkg = manifest.load_package(_with_manifest(change))
    found = {(d.code, d.pointer) for d in pkg.diagnostics}
    assert not pkg.ok
    assert any(c == code and (pointer is None or p == pointer) for c, p in found), found


@pytest.mark.parametrize(
    "path", ["../x.mjs", "/abs.js", "handlers/../../etc", "public/.hidden", "a\\b", "other/x.txt"]
)
def test_unsafe_or_unknown_paths_are_refused(path):
    files = [*_files(EXAMPLES / "requests"), (path, b"x")]
    pkg = manifest.load_package(files)
    assert not pkg.ok
    assert {d.code for d in pkg.diagnostics} & {"path_invalid", "path_not_allowed"}


def test_handler_imports_are_refused():
    files = dict(_files(EXAMPLES / "requests"))
    files["handlers/approve.mjs"] = b"import fs from 'node:fs';\n" + files["handlers/approve.mjs"]
    pkg = manifest.load_package(list(files.items()))
    assert "handler_import" in {d.code for d in pkg.diagnostics}


def test_model_changes_are_additive_only():
    m = json.loads((EXAMPLES / "requests" / "microapp.json").read_text())
    old = manifest.data_model(m)
    new = json.loads(json.dumps(old))
    new["requests"]["fields"]["priority"] = {"type": "integer", "minimum": 0, "maximum": 5}
    delta = ddl.diff("a_" + "0" * 32, old, new)
    assert delta.fields_added == ["requests.priority"] and not delta.destructive
    new["requests"]["fields"]["title"]["maxLength"] = 10
    del new["requests"]["fields"]["description"]
    reasons = [d["reason"] for d in ddl.diff("a_" + "0" * 32, old, new).destructive]
    assert len(reasons) == 2


def test_ddl_identifiers_and_literals_cannot_be_injected():
    with pytest.raises(ValueError):
        ddl.ident('x"; DROP TABLE y; --')
    assert ddl.literal({"type": "string"}, "a'b") == "'a''b'"


# ---------- plan / apply ----------


async def _plan_and_apply(
    client, user, root=EXAMPLES / "requests", key="k-apply-0001", asset_id=None
):
    body = {"files": _payload(root)}
    if asset_id:
        body["asset_id"] = asset_id
    r = await client.post("/api/micro-applications/plans", json=body, headers=bearer(user))
    assert r.status_code == 201, r.text
    plan = r.json()
    r = await client.post(
        f"/api/micro-applications/plans/{plan['plan_id']}/apply",
        json={
            "digest": plan["release_digest"],
            "expected_generation": plan["expected_generation"],
            "idempotency_key": key,
        },
        headers=bearer(user),
    )
    return plan, r


async def test_plan_refuses_a_browser_session(client, session):
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)
    r = await client.post(
        "/api/micro-applications/plans", json={"files": _payload(EXAMPLES / "requests")}
    )
    assert r.status_code == 403
    assert r.json()["code"] == "programmatic_auth_required"


async def test_plan_reports_diagnostics_and_compile_errors(client, session):
    user = await mk_user(session)
    await session.commit()
    files = _payload(EXAMPLES / "requests")
    for f in files:
        if f["path"] == "handlers/approve.mjs":
            f["content_text"] = "SYNTAX_ERROR export default"
    r = await client.post(
        "/api/micro-applications/plans", json={"files": files}, headers=bearer(user)
    )
    assert r.status_code == 400
    body = r.json()
    assert body["code"] == "manifest_invalid"
    assert body["file"] == "handlers/approve.mjs"


async def test_apply_is_idempotent_and_binds_the_planned_package(client, session):
    user = await mk_user(session)
    await session.commit()
    plan, first = await _plan_and_apply(client, user)
    assert first.status_code == 202
    op = first.json()
    again = await client.post(
        f"/api/micro-applications/plans/{plan['plan_id']}/apply",
        json={
            "digest": plan["release_digest"],
            "expected_generation": 0,
            "idempotency_key": "k-apply-0001",
        },
        headers=bearer(user),
    )
    assert again.status_code == 200
    assert again.json()["operation_id"] == op["operation_id"] and again.json()["replayed"] is True
    other = await client.post(
        f"/api/micro-applications/plans/{plan['plan_id']}/apply",
        json={
            "digest": "sha256:" + "0" * 64,
            "expected_generation": 0,
            "idempotency_key": "k-apply-0001",
        },
        headers=bearer(user),
    )
    assert other.status_code == 409 and other.json()["code"] == "idempotency_key_reused"
    ops = (
        await session.scalars(
            select(MicroAppOperation).where(MicroAppOperation.actor_id == user.id)
        )
    ).all()
    assert len(ops) == 1
    assets = (await session.scalars(select(Asset).where(Asset.owner_id == user.id))).all()
    assert len(assets) == 1 and assets[0].kind == "micro_application"


async def test_editor_prepares_but_cannot_publish(client, session):
    owner = await mk_user(session)
    editor = await mk_user(session)
    await session.commit()
    _, r = await _plan_and_apply(client, owner)
    asset_id = r.json()["asset_id"]
    session.add(AssetShare(asset_id=uuid.UUID(asset_id), user_id=editor.id, role="editor"))
    await session.commit()
    plan, applied = await _plan_and_apply(client, editor, asset_id=asset_id, key="k-editor-0001")
    assert plan["can_apply"] is False
    assert applied.status_code == 403 and applied.json()["code"] == "publish_permission_required"


# ---------- generic routes refuse the kind ----------


async def _microapp_asset(session, owner) -> Asset:
    asset = Asset(
        slug=generate_slug(),
        owner_id=owner.id,
        kind="micro_application",
        title="App",
        storage_prefix=f"assets/{uuid.uuid4()}",
        entry_path="public/index.html",
        version=1,
    )
    session.add(asset)
    await session.flush()
    storage = storage_from_url(get_settings().storage_url)
    from app.services.upload import one_chunk

    for path, data in {
        "microapp.json": b"{}",
        "handlers/h.mjs": SECRET.encode(),
        "README.md": f"# {SECRET}".encode(),
        "public/index.html": b"<p>hi</p>",
    }.items():
        await storage.put(f"{asset.storage_prefix}/v1/{path}", one_chunk(data))
    session.add(
        AssetVersion(
            asset_id=asset.id,
            version=1,
            storage_prefix=f"{asset.storage_prefix}/v1",
            change_note=f"note {SECRET}",
        )
    )
    await session.commit()
    return asset


async def test_generic_read_paths_never_return_the_package(client, session):
    owner = await mk_user(session)
    viewer = await mk_user(session)
    await session.commit()
    asset = await _microapp_asset(session, owner)
    session.add(AssetShare(asset_id=asset.id, user_id=viewer.id, role="viewer"))
    await session.commit()
    for who in (owner, viewer):
        await login_as(client, who)
        s, i = asset.slug, asset.id
        paths = [
            f"/api/assets/by-slug/{s}/tree",
            f"/api/assets/by-slug/{s}/download",
            f"/api/assets/by-slug/{s}/file?path=handlers/h.mjs",
            f"/api/assets/by-slug/{s}/static/handlers/h.mjs",
            f"/api/assets/by-slug/{s}/render",
            f"/api/assets/by-slug/{s}/source",
            f"/api/assets/by-slug/{s}/graph",
            f"/api/assets/by-slug/{s}/html-grant",
            f"/api/assets/by-slug/{s}/agent-view",
            f"/api/assets/by-slug/{s}/files-mcp",
            f"/api/assets/by-slug/{s}/file-mcp?path=handlers/h.mjs",
            f"/api/assets/by-slug/{s}/outline",
            f"/api/assets/{i}/versions",
            f"/api/assets/{i}/versions/1/diff/1?path=handlers/h.mjs",
            f"/api/assets/by-slug/{s}/doc",
            f"/api/assets/by-slug/{s}/meta",
            f"/api/assets/{i}",
            "/api/assets/search?q=SECRET",
            "/api/assets/search-mcp?q=SECRET",
            "/api/assets/index",
        ]
        for path in paths:
            r = await client.get(path)
            # A publisher's history carries the change notes, as /releases does.
            if not (who is owner and path.endswith("/versions")):
                assert SECRET not in r.text, (who.email, path, r.status_code)
            restricted = ("/tree", "/download", "/source", "/files-mcp")
            # The package history is the publishers' (the owner's), not a viewer's.
            if path.endswith(restricted) or (path.endswith("/versions") and who is viewer):
                assert r.json()["code"] == "microapp_source_restricted", path


async def test_generic_write_paths_refuse_the_kind(client, session):
    owner = await mk_user(session)
    await session.commit()
    asset = await _microapp_asset(session, owner)
    await login_as(client, owner)
    h = {"Origin": get_settings().base_url}
    i = asset.id
    checks = [
        await client.put(
            f"/api/assets/{i}/content", json={"content": "x", "path": "handlers/h.mjs"}, headers=h
        ),
        await client.post(f"/api/assets/{i}/versions/1/restore", headers=h),
        await client.post(
            f"/api/assets/{i}/versions", files={"files": ("index.html", b"x")}, headers=h
        ),
        await client.post(
            f"/api/assets/{i}/files/empty", json={"path": "handlers/x.mjs"}, headers=h
        ),
        await client.delete(f"/api/assets/{i}/files?path=handlers/h.mjs", headers=h),
    ]
    for r in checks:
        assert r.status_code == 409 and r.json()["code"] == "microapp_requires_agent_api", r.text
    versions = (await session.scalars(select(AssetVersion).where(AssetVersion.asset_id == i))).all()
    assert len(versions) == 1


async def test_plain_upload_with_a_manifest_is_refused(client, session):
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)
    r = await client.post(
        "/api/assets/html",
        files=[
            ("files", ("microapp.json", b"{}", "application/json")),
            ("files", ("index.html", b"<p>x", "text/html")),
        ],
        data={"paths": ["microapp.json", "index.html"]},
        headers={"Origin": get_settings().base_url},
    )
    assert r.status_code == 409 and r.json()["code"] == "microapp_requires_agent_api"


async def test_metadata_patch_does_not_touch_platform_state(client, session):
    owner = await mk_user(session)
    await session.commit()
    _, r = await _plan_and_apply(client, owner)
    asset_id = r.json()["asset_id"]
    await login_as(client, owner)
    env_before = await session.scalar(
        select(MicroAppEnvironment).where(MicroAppEnvironment.asset_id == uuid.UUID(asset_id))
    )
    snapshot = (
        env_before.desired_state,
        env_before.active_release_id,
        env_before.control_generation,
    )
    r = await client.patch(
        f"/api/assets/{asset_id}/meta",
        json={"properties": {"desired_state": "enabled", "active_release_id": str(uuid.uuid4())}},
        headers={"Origin": get_settings().base_url},
    )
    await session.refresh(env_before)
    assert (
        env_before.desired_state,
        env_before.active_release_id,
        env_before.control_generation,
    ) == snapshot


# ---------- rights, grants, launch, internal API ----------


async def test_business_permissions_come_only_from_grants_and_follow_membership(client, session):
    owner = await mk_user(session)
    member = await mk_user(session)
    external = await mk_user(session, role="external")
    await session.commit()
    _, r = await _plan_and_apply(client, owner)
    aid = uuid.UUID(r.json()["asset_id"])
    project = Project(slug=generate_slug(), name="P")
    session.add(project)
    await session.flush()
    pm = ProjectMember(
        project_id=project.id, user_id=member.id, role="viewer", accepted_at=utc_now()
    )
    session.add(pm)
    session.add(AssetShare(asset_id=aid, user_id=member.id, role="viewer"))
    session.add(AssetShare(asset_id=aid, user_id=external.id, role="viewer"))
    session.add(
        MicroAppGrant(
            asset_id=aid, environment="prod", permission="requests.read", project_id=project.id
        )
    )
    await session.commit()
    asset = await session.get(Asset, aid)
    assert await access.granted_permissions(session, owner, aid) == set()
    assert await access.granted_permissions(session, member, aid) == {"requests.read"}
    assert (await access.rights(session, external, asset)).use is False
    assert (await access.rights(session, member, asset)).control is False
    await session.delete(pm)
    await session.commit()
    assert await access.granted_permissions(session, member, aid) == set()


async def test_internal_api_needs_the_service_token(client, session):
    r = await client.post(
        "/api/internal/microapps/authorize", json={"asset": "0" * 32, "environment": "prod"}
    )
    assert r.status_code == 404
    r = await client.post(
        "/api/internal/microapps/authorize",
        json={"asset": "0" * 32, "environment": "prod"},
        headers={"X-ICS-Service-Token": "wrong"},
    )
    assert r.status_code == 404


async def test_launch_code_is_single_use_and_bound_to_host_and_state(client, session):
    owner = await mk_user(session)
    await session.commit()
    _, r = await _plan_and_apply(client, owner)
    env = await session.scalar(
        select(MicroAppEnvironment).where(
            MicroAppEnvironment.asset_id == uuid.UUID(r.json()["asset_id"])
        )
    )
    settings = get_settings()
    host = f"a-{env.asset_hex}-prod.{settings.microapps_app_host_suffix}"
    code = await runtime.issue_launch_code(session, settings, owner, host, "state-1")
    with pytest.raises(InvalidInputError):
        await runtime.exchange_launch_code(code, host, "other-state")
    code = await runtime.issue_launch_code(session, settings, owner, host, "state-1")
    with pytest.raises(InvalidInputError):
        await runtime.exchange_launch_code(code, "a-" + "1" * 32 + "-prod.x", "state-1")
    code = await runtime.issue_launch_code(session, settings, owner, host, "state-1")
    ok = await runtime.exchange_launch_code(code, host, "state-1")
    assert ok["asset_hex"] == env.asset_hex
    with pytest.raises(InvalidInputError):
        await runtime.exchange_launch_code(code, host, "state-1")


async def test_control_suspend_and_enable_change_desired_state_only(client, session):
    owner = await mk_user(session)
    await session.commit()
    _, r = await _plan_and_apply(client, owner)
    aid = r.json()["asset_id"]
    await login_as(client, owner)
    h = {"Origin": get_settings().base_url}
    env = await session.scalar(
        select(MicroAppEnvironment).where(MicroAppEnvironment.asset_id == uuid.UUID(aid))
    )
    gen = env.control_generation
    stale = await client.post(
        f"/api/micro-applications/{aid}/control",
        json={"action": "suspend", "expected_generation": gen + 5, "idempotency_key": "ctl-000001"},
        headers=h,
    )
    assert stale.status_code == 409 and stale.json()["code"] == "generation_conflict"
    r = await client.post(
        f"/api/micro-applications/{aid}/control",
        json={"action": "suspend", "expected_generation": gen, "idempotency_key": "ctl-000002"},
        headers=h,
    )
    assert r.status_code == 200 and r.json()["status"] == "succeeded"
    await session.refresh(env)
    assert env.desired_state == "suspended"
    r = await client.post(
        f"/api/micro-applications/{aid}/control",
        json={
            "action": "enable",
            "expected_generation": env.control_generation,
            "idempotency_key": "ctl-000003",
        },
        headers=h,
    )
    await session.refresh(env)
    assert env.desired_state == "enabled"
    detail = (await client.get(f"/api/micro-applications/{aid}")).json()
    assert detail["runtime"]["state"] == "sleeping"


# ---------- publication with real provisioning ----------

PROVISIONER = os.environ.get("ICS_MICROAPPS_TEST_PROVISIONER_URL")
needs_pg = pytest.mark.skipif(not PROVISIONER, reason="ICS_MICROAPPS_TEST_PROVISIONER_URL not set")


@pytest.fixture
async def apps_db(monkeypatch, session):
    worker = os.environ.get("PYTEST_XDIST_WORKER", "master")
    name = f"ics_apps_test_{worker}"
    admin = await asyncpg.connect(PROVISIONER)
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE "{name}" TEMPLATE template0')
        await admin.execute(f'REVOKE ALL ON DATABASE "{name}" FROM PUBLIC')
    finally:
        await admin.close()
    url = PROVISIONER.rsplit("/", 1)[0] + f"/{name}"
    conn = await asyncpg.connect(url)
    await conn.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
    await conn.close()
    monkeypatch.setattr(get_settings(), "microapps_apps_database_url", url)
    monkeypatch.setattr(get_settings(), "microapps_runtime_db_host", urlparse(PROVISIONER).hostname)
    yield url
    # Roles are cluster-wide and outlive the scratch database: drop the ones
    # this test created (named after its own assets only).
    roles = [
        r
        for b in (await session.scalars(select(MicroAppSchemaBinding))).all()
        for r in (b.runtime_role, b.owner_role)
    ]
    admin = await asyncpg.connect(PROVISIONER)
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        for role in roles:
            if await admin.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", role):
                await admin.execute(f'DROP ROLE "{role}"')
    finally:
        await admin.close()


async def _publish(session, op_id) -> str:
    return await publish.process(session, get_settings(), op_id)


def _names_for(asset_id: str, db: str) -> Names:
    n = Names.for_asset(uuid.UUID(asset_id).hex, "prod")
    return Names(db, n.schema, n.owner, n.runtime)


@needs_pg
async def test_publication_provisions_isolated_schemas_and_survives_a_crash(
    client, session, apps_db, monkeypatch
):
    owner = await mk_user(session)
    await session.commit()
    _, ra = await _plan_and_apply(client, owner, key="k-pub-a-0001")
    _, rb = await _plan_and_apply(client, owner, root=EXAMPLES / "equipment", key="k-pub-b-0001")
    a, b = ra.json(), rb.json()

    # Simulated worker death right after the package commit: same version on resume.
    monkeypatch.setattr(get_settings(), "microapps_fault_injection", True)
    from app.redis_client import get_redis

    op_a = await session.get(MicroAppOperation, a["operation_id"])
    await get_redis().set(f"microapp:fault:{op_a.plan_id}", "crash_after:package")
    assert await _publish(session, a["operation_id"]) == "crashed"
    op_a = await session.get(MicroAppOperation, a["operation_id"], populate_existing=True)
    first_version = op_a.asset_version_id
    op_a.lease_until = None  # lease expiry, as the sweeper would see it
    await session.commit()
    assert await _publish(session, a["operation_id"]) == "succeeded"
    assert await _publish(session, b["operation_id"]) == "succeeded"
    op_a = await session.get(MicroAppOperation, a["operation_id"], populate_existing=True)
    assert op_a.asset_version_id == first_version
    assert (
        len(
            (
                await session.scalars(
                    select(AssetVersion).where(AssetVersion.asset_id == uuid.UUID(a["asset_id"]))
                )
            ).all()
        )
        == 1
    )

    # Runtime role A against schema B: no data, no role switch, no DDL.
    db = urlparse(apps_db).path.lstrip("/")
    na, nb = _names_for(a["asset_id"], db), _names_for(b["asset_id"], db)
    bind = await runtime.binding(session, get_settings(), uuid.UUID(a["asset_id"]), "prod")
    host = urlparse(PROVISIONER)
    conn = await asyncpg.connect(
        host=host.hostname,
        port=host.port or 5432,
        user=bind["user"],
        password=bind["password"],
        database=db,
    )
    try:
        await conn.execute(
            f'INSERT INTO "{na.schema}".requests (id, created_by, title) VALUES ($1, $2, $3)',
            uuid.uuid4(),
            uuid.uuid4(),
            "ok",
        )
        for stmt in (
            f'SELECT * FROM "{nb.schema}".equipment',
            f"INSERT INTO \"{nb.schema}\".equipment (id, created_by, name, quantity, available) VALUES (gen_random_uuid(), gen_random_uuid(), 'x', 1, 1)",
            f'SET ROLE "{nb.runtime}"',
            f'SET ROLE "{na.owner}"',
            f'CREATE TABLE "{na.schema}".evil (x int)',
            f'DROP TABLE "{na.schema}".requests',
            f'SELECT * FROM "{na.schema}"."_ics_schema_migrations"',
            f'UPDATE "{na.schema}"."_ics_audit" SET action = \'x\'',
        ):
            with pytest.raises(asyncpg.PostgresError):
                await conn.execute(stmt)
        await conn.execute(f'SET search_path = "{nb.schema}"')
        with pytest.raises(asyncpg.PostgresError):
            await conn.execute("SELECT * FROM equipment")
    finally:
        await conn.close()
    # Hard delete of the asset leaves a cleanup order; cleanup drops both roles.
    asset_a = await session.get(Asset, uuid.UUID(a["asset_id"]))
    await session.delete(asset_a)
    await session.commit()
    order = await session.scalar(
        select(MicroAppCleanupOrder).where(MicroAppCleanupOrder.schema_name == na.schema)
    )
    assert order is not None and order.status == "pending"
    from app.jobs.tasks.micro_applications import _cleanup

    cleaned = await _cleanup(get_settings())
    await session.refresh(order)
    assert cleaned >= 1, order.last_error
    check = await asyncpg.connect(apps_db)
    try:
        assert not await check.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", na.runtime)
        assert not await check.fetchval("SELECT 1 FROM pg_namespace WHERE nspname = $1", na.schema)
    finally:
        await check.close()

    # The runtime role cannot reach the ICS metadata database at all. That is
    # enforced by pg_hba.conf, so only a server with the profile's HBA rules
    # (local/microapps/pg_hba.conf) can prove it.
    ics = urlparse(get_settings().database_url.replace("+asyncpg", ""))
    if os.environ.get("ICS_MICROAPPS_TEST_HBA") != "strict":
        pytest.skip("HBA isolation needs the local profile's pg_hba.conf")
    with pytest.raises((asyncpg.PostgresError, OSError)):
        bad = await asyncpg.connect(
            host=ics.hostname,
            port=ics.port or 5432,
            user=bind["user"],
            password=bind["password"],
            database=ics.path.lstrip("/"),
        )
        await bad.close()


@needs_pg
async def test_failed_publication_keeps_the_active_release(client, session, apps_db, monkeypatch):
    owner = await mk_user(session)
    await session.commit()
    _, r = await _plan_and_apply(client, owner, key="k-fail-0001")
    first = r.json()
    assert await _publish(session, first["operation_id"]) == "succeeded"
    env = await session.scalar(
        select(MicroAppEnvironment).where(
            MicroAppEnvironment.asset_id == uuid.UUID(first["asset_id"])
        )
    )
    active = env.active_release_id

    monkeypatch.setattr(get_settings(), "microapps_fault_injection", True)
    plan, r2 = await _plan_and_apply(client, owner, asset_id=first["asset_id"], key="k-fail-0002")
    from app.redis_client import get_redis

    await get_redis().set(f"microapp:fault:{plan['plan_id']}", "fail:verify")
    assert await _publish(session, r2.json()["operation_id"]) == "failed"
    await session.refresh(env)
    assert env.active_release_id == active
    op = await session.get(MicroAppOperation, r2.json()["operation_id"], populate_existing=True)
    assert op.status == "failed" and op.error_code == "fault_injected"
    rel = await session.get(MicroAppRelease, op.release_id)
    assert rel.status == "failed"
    binding = await session.scalar(
        select(MicroAppSchemaBinding).where(MicroAppSchemaBinding.environment_id == env.id)
    )
    assert binding is not None
    # The history says which package runs: the failed one is not current.
    rows = (
        await client.get(f"/api/assets/{first['asset_id']}/versions", headers=bearer(owner))
    ).json()
    assert [(r["version"], r["release_status"], r["is_current"]) for r in rows] == [
        (2, "failed", False),
        (1, "active", True),
    ]


@needs_pg
async def test_an_app_whose_first_publication_fails_leaves_the_lists(
    client, session, apps_db, monkeypatch
):
    owner = await mk_user(session)
    await session.commit()
    monkeypatch.setattr(get_settings(), "microapps_fault_injection", True)
    plan, r = await _plan_and_apply(client, owner, key="k-unborn-001")
    from app.redis_client import get_redis

    await get_redis().set(f"microapp:fault:{plan['plan_id']}", "fail:verify")
    op_id = r.json()["operation_id"]
    assert await _publish(session, op_id) == "failed"
    asset = await session.get(Asset, uuid.UUID(r.json()["asset_id"]), populate_existing=True)
    assert asset.deleted_at is not None
    # Its author still reads why.
    status_ = await client.get(f"/api/micro-applications/operations/{op_id}", headers=bearer(owner))
    assert status_.json()["error"]["code"] == "fault_injected"


@needs_pg
async def test_watchers_hear_of_an_app_once_it_runs_and_hand_edits_stay(
    client, session, apps_db, monkeypatch
):
    from app.services.notifications import events

    heard: list[tuple[str, int | None]] = []

    async def created(asset, actor):
        heard.append(("created", None))

    async def updated(asset, version, actor, settings):
        heard.append(("updated", version))

    monkeypatch.setattr(events, "emit_created", created)
    monkeypatch.setattr(events, "emit_updated", updated)
    owner = await mk_user(session)
    await session.commit()
    _, r = await _plan_and_apply(client, owner, key="k-born-0001")
    aid = r.json()["asset_id"]
    assert heard == []  # accepted is not born
    assert await _publish(session, r.json()["operation_id"]) == "succeeded"
    assert heard == [("created", None)]

    asset = await session.get(Asset, uuid.UUID(aid), populate_existing=True)
    asset.title = "Renamed by hand"
    asset.summary, asset.summary_source = "Written by hand", "human"
    await session.commit()
    _, r2 = await _plan_and_apply(client, owner, asset_id=aid, key="k-born-0002")
    assert await _publish(session, r2.json()["operation_id"]) == "succeeded"
    assert heard[-1] == ("updated", 2)
    # `summary` is a deferred column: an explicit read.
    row = (
        await session.execute(select(Asset.title, Asset.summary).where(Asset.id == uuid.UUID(aid)))
    ).one()
    assert tuple(row) == ("Renamed by hand", "Written by hand")


@needs_pg
async def test_a_configured_reader_role_reads_every_table_and_writes_none(
    client, session, apps_db, monkeypatch
):
    worker = os.environ.get("PYTEST_XDIST_WORKER", "master")
    reader = f"ics_apps_test_reader_{worker}"
    admin = await asyncpg.connect(PROVISIONER)
    try:
        await admin.execute(f'DROP ROLE IF EXISTS "{reader}"')
        await admin.execute(f'CREATE ROLE "{reader}" NOLOGIN')
    finally:
        await admin.close()
    monkeypatch.setattr(get_settings(), "microapps_reader_role", reader)
    try:
        owner = await mk_user(session)
        await session.commit()
        _, r = await _plan_and_apply(client, owner, key="k-reader-0001")
        op = r.json()
        assert await _publish(session, op["operation_id"]) == "succeeded"
        names = _names_for(op["asset_id"], urlparse(apps_db).path.lstrip("/"))
        conn = await asyncpg.connect(apps_db)
        try:
            # Names inside the schema resolve only with its USAGE: check as the owner.
            await conn.execute(f'SET ROLE "{names.owner}"')
            table = f'"{names.schema}"."requests"'

            def can(priv):
                return conn.fetchval("SELECT has_table_privilege($1, $2, $3)", reader, table, priv)

            assert await can("SELECT")
            for priv in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                assert not await can(priv), priv
            assert await conn.fetchval(
                "SELECT has_table_privilege($1, $2, 'SELECT')",
                reader,
                f'"{names.schema}"."_ics_audit"',
            )
            # Tables a later migration adds are readable too (default privileges).
            await conn.execute(f'CREATE TABLE "{names.schema}".later (id int)')
            assert await conn.fetchval(
                "SELECT has_table_privilege($1, $2, 'SELECT')", reader, f'"{names.schema}".later'
            )
            await conn.execute("RESET ROLE")
            assert await provisioning.verify(conn, names, ["requests"], reader) == []
            assert not await provisioning.grant_reader(conn, names, "no_such_role_x")
        finally:
            await conn.close()
    finally:
        # The reader's grants live in the scratch database: drop it first.
        admin = await asyncpg.connect(PROVISIONER)
        try:
            await admin.execute(
                f'DROP DATABASE IF EXISTS "{urlparse(apps_db).path.lstrip("/")}" WITH (FORCE)'
            )
            await admin.execute(f'DROP ROLE IF EXISTS "{reader}"')
        finally:
            await admin.close()


# ---------- seed rows and the document view ----------


def _template_with(change=None, extra=None) -> list[tuple[str, bytes]]:
    files = dict(_files(TEMPLATE))
    if change:
        m = json.loads(files["microapp.json"])
        change(m)
        files["microapp.json"] = json.dumps(m).encode()
    files.update(extra or {})
    return list(files.items())


def test_the_template_declares_a_document_view_and_seed_rows():
    pkg = manifest.load_package(_files(TEMPLATE))
    assert pkg.ok and pkg.manifest["document"] == {"endpoint": "document"}
    assert pkg.seeds["notes"][0]["pinned"] is True


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (lambda m: m.update(document={"endpoint": "nope"}), "document_endpoint_unknown"),
        (lambda m: m.update(document={"endpoint": "togglePin"}), "document_endpoint_writes"),
        (
            lambda m: m["endpoints"][1]["output"]["properties"].update(
                markdown={"type": "integer"}
            ),
            "document_output_invalid",
        ),
        (
            lambda m: m["endpoints"][1].update(path="/v1/custom/document/:id"),
            "document_endpoint_params",
        ),
    ],
)
def test_a_document_view_is_a_read_only_endpoint_returning_markdown(change, code):
    pkg = manifest.load_package(_template_with(change))
    assert code in {d.code for d in pkg.diagnostics}, [d.as_dict() for d in pkg.diagnostics]


@pytest.mark.parametrize(
    ("seed", "path", "code"),
    [
        (b'[{"text": "x", "colour": "red"}]', "seed/notes.json", "seed_field_unknown"),
        (b'[{"pinned": true}]', "seed/notes.json", "seed_field_missing"),
        (b'[{"text": null}]', "seed/notes.json", "seed_field_missing"),
        (b'[{"created_by": "x", "text": "x"}]', "seed/notes.json", "seed_field_unknown"),
        (b'{"text": "x"}', "seed/notes.json", "seed_invalid"),
        (b"[", "seed/notes.json", "seed_not_json"),
        (b"[]", "seed/ghosts.json", "seed_collection_unknown"),
        (b"[]", "seed/notes.txt", "seed_extension"),
    ],
)
def test_seed_rows_follow_the_data_model(seed, path, code):
    files = dict(_files(TEMPLATE))
    files.pop("seed/notes.json")
    files[path] = seed
    pkg = manifest.load_package(list(files.items()))
    assert code in {d.code for d in pkg.diagnostics}, [d.as_dict() for d in pkg.diagnostics]


async def test_seed_values_are_checked_by_the_broker_with_the_apps_rules(monkeypatch):
    from app.services.micro_applications import plan as plans

    sent: dict = {}

    async def broker(settings, method, path, body=None, timeout=15.0):
        sent.update(body)
        bad = {"pointer": "/0/text", "message": "text: must be a string"}
        return {"results": {}, "seeds": {"seed/notes.json": [bad]}}

    monkeypatch.setattr(plans, "broker_admin", broker)
    files = dict(_files(TEMPLATE))
    files["seed/notes.json"] = b'[{"text": 5}]'
    pkg = manifest.load_package(list(files.items()))
    diags = await plans._compile(get_settings(), pkg)
    seeds = sent["seeds"]["seed/notes.json"]
    assert seeds["rows"] == [{"text": 5}] and seeds["fields"]["text"]["type"] == "string"
    assert [(d.code, d.file, d.pointer) for d in diags] == [
        ("seed_value_invalid", "seed/notes.json", "/0/text")
    ]


def test_seed_statements_are_the_same_on_a_retried_migration():
    from app.services.micro_applications import content

    pkg = manifest.load_package(_files(TEMPLATE))
    model = manifest.data_model(pkg.manifest)
    owner = uuid.uuid4()
    imported = {"text": "It's quoted", "pinned": False, "created_at": "2026-09-25T15:22:16Z"}
    rows = {"notes": [*pkg.seeds["notes"], imported]}
    first = content.seed_statements("a_x", model, rows, created_by=owner, plan_id="plan_1")
    again = content.seed_statements("a_x", model, rows, created_by=owner, plan_id="plan_1")
    assert first == again and len(first) == 1
    assert "It''s quoted" in first[0] and f"'{owner}'::uuid" in first[0]
    # An imported record keeps its date; the others get the migration's.
    assert "'2026-09-25T15:22:16Z'::timestamptz" in first[0] and "now()" in first[0]
    assert content.seed_statements("a_x", model, {}, created_by=owner, plan_id="p") == []


def test_app_changes_speak_in_the_apps_terms():
    from app.services.micro_applications.changes import manifest_changes

    old = json.loads((EXAMPLES / "requests" / "microapp.json").read_text())
    new = json.loads(json.dumps(old))
    new["roles"]["reviewer"]["permissions"].remove("requests.read")
    new["permissions"]["requests.export"] = {"label": "Export"}
    new["roles"]["reviewer"]["permissions"].append("requests.export")
    new["database"]["collections"]["requests"]["fields"]["priority"] = {
        "type": "integer",
        "minimum": 1,
        "maximum": 3,
    }
    new["endpoints"] = [e for e in new["endpoints"] if e["name"] != "document"]
    del new["document"]
    got = {(c["area"], c["name"], c["change"]): c["detail"] for c in manifest_changes(old, new)}
    assert got[("role", "reviewer", "changed")] == "+requests.export -requests.read"
    assert ("permission", "requests.export", "added") in got
    assert got[("collection", "requests", "changed")] == "fields +priority"
    assert ("endpoint", "document", "removed") in got
    assert ("setting", "document", "removed") in got
    assert manifest_changes(old, old) == []


async def test_links_point_at_an_app_never_into_its_package(client, session):
    from tests.conftest import mk_asset

    owner = await mk_user(session)
    author = await mk_user(session)
    stranger = await mk_user(session)
    await session.commit()
    app_asset = await _microapp_asset(session, owner)
    note = await mk_asset(session, author, title="Notes")
    session.add(AssetShare(asset_id=app_asset.id, user_id=author.id, role="viewer"))
    await session.commit()

    await login_as(client, author)
    h = {"Origin": get_settings().base_url}
    url = f"/api/assets/{note.id}/relations"
    for location in ({"target_path": "nope.md"}, {"target_anchor": "anything"}):
        r = await client.post(
            url,
            json={"relation_type": "references", "target_id": str(app_asset.id), **location},
            headers=h,
        )
        # Listing the package's paths or headings would show its sources.
        assert r.status_code == 409 and r.json()["code"] == "microapp_not_addressable", r.text
        assert SECRET not in r.text and "handlers/" not in r.text
    whole = await client.post(
        url, json={"relation_type": "references", "target_id": str(app_asset.id)}, headers=h
    )
    assert whole.status_code == 201, whole.text

    # Rescanning tells a stranger nothing about the kind; the owner learns
    # an app has no links to extract.
    await login_as(client, stranger)
    hidden = await client.post(f"/api/assets/{app_asset.id}/relations/rescan", headers=h)
    assert hidden.status_code == 404
    await login_as(client, owner)
    own = await client.post(f"/api/assets/{app_asset.id}/relations/rescan", headers=h)
    assert own.status_code == 409 and own.json()["code"] == "microapp_not_addressable"


async def test_values_a_manifest_states_are_checked_by_the_broker(monkeypatch):
    from app.services.micro_applications import plan as plans

    def with_values(m):
        notes = m["database"]["collections"]["notes"]
        notes["fields"]["text"]["default"] = "x" * 5000
        notes["fields"]["pinned"]["default"] = False
        m["capabilities"]["notes.list_own"]["conditions"] = {"pinned": "yes"}

    sent: dict = {}

    async def broker(settings, method, path, body=None, timeout=15.0):
        sent.update(body)
        bad = [
            {"pointer": v["pointer"], "code": v["code"], "message": "rejected"}
            for v in body["values"]
            if v["pointer"].endswith(("/text/default", "/conditions/pinned"))
        ]
        return {"results": {}, "seeds": {}, "values": bad}

    monkeypatch.setattr(plans, "broker_admin", broker)
    pkg = manifest.load_package(_template_with(with_values))
    assert pkg.ok, [d.as_dict() for d in pkg.diagnostics]
    diags = await plans._compile(get_settings(), pkg)
    stated = {v["pointer"]: v["value"] for v in sent["values"]}
    assert stated["/database/collections/notes/fields/pinned/default"] is False
    # Each field goes once; the values name it by pointer.
    assert sent["fields"]["/database/collections/notes/fields/pinned"]["type"] == "boolean"
    assert all(v["field"] in sent["fields"] for v in sent["values"])
    assert {(d.code, d.pointer) for d in diags} == {
        ("default_invalid", "/database/collections/notes/fields/text/default"),
        ("condition_value_invalid", "/capabilities/notes.list_own/conditions/pinned"),
    }


async def test_deleting_an_app_drops_its_roles_with_its_shares(client, session):
    owner = await mk_user(session)
    bob = await mk_user(session)
    await session.commit()
    asset = await _microapp_asset(session, owner)
    session.add(
        MicroAppGrant(
            asset_id=asset.id, environment="prod", permission="role:reader", user_id=bob.id
        )
    )
    await session.commit()
    await login_as(client, owner)
    r = await client.delete(f"/api/assets/{asset.id}", headers={"Origin": get_settings().base_url})
    assert r.status_code == 204
    # An undelete must not bring back roles the owner may no longer want.
    left = await session.scalars(select(MicroAppGrant).where(MicroAppGrant.asset_id == asset.id))
    assert left.all() == []


async def test_with_micro_applications_off_their_history_is_off_too(client, session, monkeypatch):
    owner = await mk_user(session)
    await session.commit()
    asset = await _microapp_asset(session, owner)
    monkeypatch.setattr(get_settings(), "microapps_enabled", False)
    r = await client.get(f"/api/assets/{asset.id}/versions", headers=bearer(owner))
    assert r.status_code == 404 and r.json()["code"] == "microapps_disabled"


async def test_a_plan_counts_against_the_owners_quota(client, session):
    owner = await mk_user(session)
    owner.storage_quota_bytes = 100
    await session.commit()
    r = await client.post(
        "/api/micro-applications/plans", json={"files": _payload(TEMPLATE)}, headers=bearer(owner)
    )
    assert r.status_code == 413 and r.json()["code"] == "storage_quota_exceeded"


async def test_plans_are_rate_limited_per_person(client, session, monkeypatch):
    from app import ratelimit

    monkeypatch.setattr(
        ratelimit,
        "MICROAPP_PLAN",
        ratelimit.RateLimit(f"mp_{uuid.uuid4().hex}", limit=1, window_seconds=60),
    )
    owner = await mk_user(session)
    await session.commit()
    body = {"files": _payload(TEMPLATE)}
    first = await client.post("/api/micro-applications/plans", json=body, headers=bearer(owner))
    again = await client.post("/api/micro-applications/plans", json=body, headers=bearer(owner))
    assert first.status_code == 201 and again.status_code == 429
    assert again.headers["Retry-After"]


async def test_expired_plans_and_their_packages_are_dropped(client, session, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.jobs.tasks import micro_applications as jobs

    # The module-level SessionLocal may hold a connection of another test's
    # event loop; bind the sweeper to this test's engine.
    monkeypatch.setattr(
        jobs, "SessionLocal", async_sessionmaker(session.bind, expire_on_commit=False)
    )
    owner = await mk_user(session)
    await session.commit()
    r = await client.post(
        "/api/micro-applications/plans", json={"files": _payload(TEMPLATE)}, headers=bearer(owner)
    )
    plan_id = r.json()["plan_id"]
    row = await session.get(MicroAppPlan, plan_id)
    prefix = row.storage_prefix
    row.expires_at = datetime.now(UTC) - timedelta(days=2)
    await session.commit()
    assert await jobs._drop_expired_plans(get_settings()) >= 1
    session.expire_all()
    assert await session.get(MicroAppPlan, plan_id) is None
    storage = storage_from_url(get_settings().storage_url)
    assert await storage.list_prefix_stats(f"{prefix}/") == []


@needs_pg
async def test_a_release_carries_its_authors_note_and_a_new_app_its_changes(
    client, session, apps_db
):
    owner = await mk_user(session)
    await session.commit()
    body = {"files": _payload(TEMPLATE), "change_note": "  First notes app  "}
    plan = (
        await client.post("/api/micro-applications/plans", json=body, headers=bearer(owner))
    ).json()
    # A new app: everything it brings.
    assert ("role", "reader", "added") in {
        (c["area"], c["name"], c["change"]) for c in plan["app_changes"]
    }
    r = await client.post(
        f"/api/micro-applications/plans/{plan['plan_id']}/apply",
        json={
            "digest": plan["release_digest"],
            "expected_generation": plan["expected_generation"],
            "idempotency_key": "k-note-00001",
        },
        headers=bearer(owner),
    )
    assert await _publish(session, r.json()["operation_id"]) == "succeeded"
    rows = (
        await client.get(f"/api/assets/{r.json()['asset_id']}/versions", headers=bearer(owner))
    ).json()
    assert rows[0]["change_note"] == "First notes app"
