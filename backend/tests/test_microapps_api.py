"""Micro-applications: management and internal API around a published app,
the Arq tasks and control edge cases. Shares the fixtures of
`test_microapps.py` (publication with real provisioning needs
ICS_MICROAPPS_TEST_PROVISIONER_URL)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.domain_errors import InvalidInputError
from app.models import (
    AssetShare,
    MicroAppEnvironment,
    MicroAppLog,
    MicroAppOperation,
    MicroAppStats,
)
from app.slug import generate_slug
from tests.conftest import login_as, mk_user
from tests.test_microapps import (  # noqa: F401  (fixtures)
    EXAMPLES,
    _enabled,
    _plan_and_apply,
    _publish,
    apps_db,
    bearer,
    needs_pg,
)

SVC = {"X-ICS-Service-Token": "svc-token-test"}


def origin() -> dict[str, str]:
    return {"Origin": get_settings().base_url}


async def _published(client, session, owner):
    _, r = await _plan_and_apply(client, owner, key=f"k-{uuid.uuid4().hex[:12]}")
    op = r.json()
    assert await _publish(session, op["operation_id"]) == "succeeded"
    env = await session.scalar(
        select(MicroAppEnvironment).where(MicroAppEnvironment.asset_id == uuid.UUID(op["asset_id"]))
    )
    return op, env


async def test_contract_sections_and_operation_reads(client, session):
    user = await mk_user(session)
    other = await mk_user(session)
    await session.commit()
    full = (await client.get("/api/micro-applications/contract", headers=bearer(user))).json()
    assert full["contract_hash"].startswith("sha256:") and "template" in full["sections"]
    one = (
        await client.get("/api/micro-applications/contract?section=limits", headers=bearer(user))
    ).json()
    assert one["content"]["max_files"] == 50 and one["contract_hash"] == full["contract_hash"]
    bad = await client.get("/api/micro-applications/contract?section=nope", headers=bearer(user))
    assert bad.status_code == 422
    _, r = await _plan_and_apply(client, user)
    op_id = r.json()["operation_id"]
    mine = await client.get(f"/api/micro-applications/operations/{op_id}", headers=bearer(user))
    assert mine.status_code == 200 and mine.json()["status"] == "pending"
    theirs = await client.get(f"/api/micro-applications/operations/{op_id}", headers=bearer(other))
    assert theirs.status_code == 404
    missing = await client.get("/api/micro-applications/operations/op_nope", headers=bearer(user))
    assert missing.status_code == 404


async def test_disabled_feature_answers_404(client, session, monkeypatch):
    user = await mk_user(session)
    await session.commit()
    monkeypatch.setattr(get_settings(), "microapps_enabled", False)
    r = await client.get("/api/micro-applications", headers=bearer(user))
    assert r.status_code == 404 and r.json()["code"] == "microapps_disabled"


async def test_apply_needs_a_key_and_matching_plan(client, session):
    user = await mk_user(session)
    await session.commit()
    r = await client.post(
        "/api/micro-applications/plans",
        json={"files": [{"path": "microapp.json", "content_text": "{}"}]},
        headers=bearer(user),
    )
    assert r.status_code == 400 and r.json()["code"] == "manifest_invalid"
    plan = (
        await client.post(
            "/api/micro-applications/plans",
            json={
                "files": [
                    {
                        "path": p.relative_to(EXAMPLES / "requests").as_posix(),
                        "content_text": p.read_text(),
                    }
                    for p in sorted((EXAMPLES / "requests").rglob("*"))
                    if p.is_file()
                ]
            },
            headers=bearer(user),
        )
    ).json()
    url = f"/api/micro-applications/plans/{plan['plan_id']}/apply"
    no_key = await client.post(
        url, json={"digest": plan["release_digest"], "expected_generation": 0}, headers=bearer(user)
    )
    assert no_key.status_code == 428
    wrong = await client.post(
        url,
        json={
            "digest": "sha256:" + "1" * 64,
            "expected_generation": 0,
            "idempotency_key": "k-wrong-001",
        },
        headers=bearer(user),
    )
    assert wrong.json()["code"] == "digest_mismatch"
    gen = await client.post(
        url,
        json={
            "digest": plan["release_digest"],
            "expected_generation": 3,
            "idempotency_key": "k-gen-0001",
        },
        headers=bearer(user),
    )
    assert gen.json()["code"] == "generation_conflict"
    mismatch = await client.post(
        url,
        json={
            "digest": plan["release_digest"],
            "expected_generation": 0,
            "idempotency_key": "k-a-000001",
        },
        headers={**bearer(user), "Idempotency-Key": "k-b-000001"},
    )
    assert mismatch.json()["code"] == "idempotency_key_mismatch"
    ok = await client.post(
        url,
        json={"digest": plan["release_digest"], "expected_generation": 0},
        headers={**bearer(user), "Idempotency-Key": "k-hdr-00001"},
    )
    assert ok.status_code == 202
    again = await client.post(
        url,
        json={
            "digest": plan["release_digest"],
            "expected_generation": 0,
            "idempotency_key": "k-other-001",
        },
        headers=bearer(user),
    )
    assert again.json()["code"] == "plan_already_applied"
    files = await client.post(
        "/api/micro-applications/plans",
        json={"files": [{"path": "a", "content_base64": "%%%"}]},
        headers=bearer(user),
    )
    assert files.json()["code"] == "base64_invalid"
    both = await client.post(
        "/api/micro-applications/plans", json={"files": [{"path": "a"}]}, headers=bearer(user)
    )
    assert both.json()["code"] == "content_required"


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_status_logs_releases_and_package(client, session):
    owner = await mk_user(session)
    viewer = await mk_user(session)
    await session.commit()
    op, env = await _published(client, session, owner)
    aid = op["asset_id"]
    generation = env.control_generation
    session.add(AssetShare(asset_id=uuid.UUID(aid), user_id=viewer.id, role="viewer"))
    await session.commit()

    await login_as(client, owner)
    listing = (await client.get("/api/micro-applications?q=Request")).json()
    item = next(i for i in listing["items"] if i["asset_id"] == aid)
    assert item["desired_state"] == "enabled" and item["active_release"] is not None
    assert item["runtime"]["state"] == "sleeping" and item["rights"]["control"] is True
    assert (await client.get("/api/micro-applications?state=suspended")).json()["total"] == 0
    detail = (await client.get(f"/api/micro-applications/{aid}")).json()
    assert "POST /api/v1/custom/requests/:id/approve" in detail["contract"]["endpoints"]

    logs = (await client.get(f"/api/micro-applications/{aid}/logs?limit=5")).json()
    assert any(x["message"] == "release activated" for x in logs["items"])
    rel = (await client.get(f"/api/micro-applications/{aid}/releases")).json()["items"]
    assert rel[0]["status"] == "active" and "digest" in rel[0]
    pkg = (await client.get(f"/api/micro-applications/{aid}/package")).json()
    assert "handlers/approve.mjs" in [f["path"] for f in pkg["files"]]
    one = (
        await client.get(f"/api/micro-applications/{aid}/package?path=handlers/approve.mjs")
    ).json()
    assert "export default" in one["content"]
    assert (await client.get(f"/api/micro-applications/{aid}/package?path=nope")).status_code == 404
    assert (
        await client.get(f"/api/micro-applications/{aid}/package?version=99")
    ).status_code == 404

    await session.refresh(viewer)
    await session.refresh(owner)
    await login_as(client, viewer)
    assert (await client.get(f"/api/micro-applications/{aid}/package")).json()[
        "code"
    ] == "publish_permission_required"
    assert (await client.get(f"/api/micro-applications/{aid}/logs")).json()[
        "code"
    ] == "control_permission_required"
    assert (await client.get(f"/api/micro-applications/{aid}/access")).json()[
        "code"
    ] == "manage_permission_required"
    rel_v = (await client.get(f"/api/micro-applications/{aid}/releases")).json()["items"]
    assert "digest" not in rel_v[0]
    c = await client.post(
        f"/api/micro-applications/{aid}/control",
        json={
            "action": "sleep",
            "expected_generation": generation,
            "idempotency_key": "ctl-viewer-1",
        },
        headers=origin(),
    )
    assert c.json()["code"] == "control_permission_required"


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_internal_broker_api(client, session):
    owner = await mk_user(session)
    await session.commit()
    op, env = await _published(client, session, owner)
    from app.models import MicroAppGrant

    session.add(
        MicroAppGrant(
            asset_id=uuid.UUID(op["asset_id"]),
            environment="prod",
            permission="requests.read",
            user_id=owner.id,
        )
    )
    await session.commit()

    auth = (
        await client.post(
            "/api/internal/microapps/authorize",
            json={"asset": env.asset_hex, "environment": "prod", "user_id": str(owner.id)},
            headers=SVC,
        )
    ).json()
    assert auth["app_use"] and auth["permissions"] == ["requests.read"] and auth["release"]["id"]
    anon = (
        await client.post(
            "/api/internal/microapps/authorize",
            json={"asset": env.asset_hex, "environment": "prod"},
            headers=SVC,
        )
    ).json()
    assert anon["user"] is None and anon["permissions"] == []
    missing = await client.post(
        "/api/internal/microapps/authorize",
        json={"asset": "f" * 32, "environment": "prod"},
        headers=SVC,
    )
    assert missing.status_code == 404

    rid = auth["release"]["id"]
    bundle = (
        await client.get(f"/api/internal/microapps/releases/{rid}/bundle", headers=SVC)
    ).json()
    assert (
        "handlers/approve.mjs" in bundle["handlers"]
        and "public/index.html" in bundle["public_files"]
    )
    assert "microapp.json" not in bundle["public_files"]
    page = await client.get(
        f"/api/internal/microapps/releases/{rid}/public?path=public/index.html", headers=SVC
    )
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    for bad in ("handlers/approve.mjs", "public/../microapp.json", "public/nope.css"):
        assert (
            await client.get(
                f"/api/internal/microapps/releases/{rid}/public?path={bad}", headers=SVC
            )
        ).status_code == 404
    binding = (
        await client.get(
            f"/api/internal/microapps/environments/{op['asset_id']}/prod/binding", headers=SVC
        )
    ).json()
    assert binding["user"].endswith("_run") and binding["password"]
    assert (
        await client.get(
            f"/api/internal/microapps/environments/{op['asset_id']}/preview/binding", headers=SVC
        )
    ).status_code == 404

    report = await client.post(
        "/api/internal/microapps/report",
        headers=SVC,
        json={
            "incarnation": "inc-1",
            "apps": [
                {
                    "asset_id": op["asset_id"],
                    "environment": "prod",
                    "state": "ready",
                    "inflight": 1,
                    "queued": 0,
                    "open_connections": 2,
                    "last_used_at": "2026-11-12T10:00:00Z",
                    "last_error_code": "execution_deadline",
                    "last_error_at": "2026-11-12T10:00:00Z",
                }
            ],
            "logs": [
                {
                    "asset_id": op["asset_id"],
                    "environment": "prod",
                    "level": "warn",
                    "source": "handler",
                    "message": "slow",
                    "fields": {"big": "x" * 3000},
                },
                {"asset_id": "not-a-uuid", "message": "x"},
            ],
        },
    )
    assert report.json() == {"apps": 1, "logs": 1}
    stats = await session.get(MicroAppStats, env.id, populate_existing=True)
    assert stats.runtime_state == "ready" and stats.last_error_code == "execution_deadline"
    line = await session.scalar(select(MicroAppLog).where(MicroAppLog.message == "slow"))
    assert line.fields == {"truncated": True}
    assert (await client.post("/api/internal/microapps/report", headers=SVC, json=[1])).json()[
        "code"
    ] == "bad_report"


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_launch_redirects_and_jobs(client, session, monkeypatch):
    owner = await mk_user(session)
    await session.commit()
    op, env = await _published(client, session, owner)
    suffix = get_settings().microapps_app_host_suffix
    host = f"{env.host_name}.{suffix}"
    assert op["app_url"] == f"https://{host}/"
    anon = await client.get(
        f"/api/micro-applications/launch?host={host}&state=s1", follow_redirects=False
    )
    assert anon.status_code == 302 and anon.headers["location"].startswith("/#login?next=")
    await login_as(client, owner)
    r = await client.get(
        f"/api/micro-applications/launch?host={host}&state=s1", follow_redirects=False
    )
    assert r.status_code == 302 and r.headers["location"].startswith(
        f"https://{host}/__ics/callback?code="
    )
    assert r.headers["referrer-policy"] == "no-referrer"
    from urllib.parse import parse_qs, urlparse

    from app.services.micro_applications import runtime

    def code_of(resp):
        return parse_qs(urlparse(resp.headers["location"]).query)["code"][0]

    # A code for the short host does not open the long one, and back.
    legacy = f"a-{env.asset_hex}-prod.{suffix}"
    with pytest.raises(InvalidInputError):
        await runtime.exchange_launch_code(code_of(r), legacy, "s1")
    old = await client.get(
        f"/api/micro-applications/launch?host={legacy}&state=s2", follow_redirects=False
    )
    assert old.headers["location"].startswith(f"https://{legacy}/__ics/callback?code=")
    ex = await runtime.exchange_launch_code(code_of(old), legacy, "s2")
    assert ex["asset_hex"] == env.asset_hex and ex["user_id"] == str(owner.id)
    for bad_host in (
        "evil.example",
        f"{generate_slug(8)}.{suffix}",
        f"{env.host_name}.evil.example",
    ):
        bad = await client.get(
            f"/api/micro-applications/launch?host={bad_host}&state=s1", follow_redirects=False
        )
        assert bad.status_code == 404

    # The broker learns which app a short host is; nothing else does.
    resolve = "/api/internal/microapps/hosts/resolve"
    known = await client.post(resolve, json={"host": host.upper()}, headers=SVC)
    assert known.json() == {"host": host, "asset_hex": env.asset_hex, "environment": "prod"}
    assert (await client.post(resolve, json={"host": legacy}, headers=SVC)).json()[
        "asset_hex"
    ] == env.asset_hex
    unknown = await client.post(resolve, json={"host": f"{generate_slug(8)}.{suffix}"}, headers=SVC)
    assert unknown.status_code == 404
    assert (await client.post(resolve, json={"host": host})).status_code == 404

    # A new release keeps the name and the address.
    _, again = await _plan_and_apply(client, owner, asset_id=op["asset_id"], key="k-host-again1")
    assert await _publish(session, again.json()["operation_id"]) == "succeeded"
    await session.refresh(env)
    assert env.host_name == host.split(".")[0]
    detail = (await client.get(f"/api/micro-applications/{op['asset_id']}")).json()
    assert detail["app_url"] == f"https://{host}/"

    from app.jobs.tasks import micro_applications as jobs

    stuck = MicroAppOperation(
        id="op_stuck1",
        action="publish:update",
        asset_id=uuid.UUID(op["asset_id"]),
        actor_id=owner.id,
        idempotency_key="k-stuck-0001",
        request_hash="h",
        status="pending",
    )
    session.add(stuck)
    await session.commit()
    from datetime import UTC, datetime, timedelta

    stuck.created_at = datetime.now(UTC) - timedelta(minutes=5)
    await session.commit()
    # The module-level SessionLocal belongs to another event loop; bind the
    # tasks to this test's engine (as tests/test_jobs_outline.py does).
    from sqlalchemy.ext.asyncio import async_sessionmaker

    monkeypatch.setattr(
        jobs, "SessionLocal", async_sessionmaker(session.bind, expire_on_commit=False)
    )
    out = await jobs.microapp_sweeper({})
    assert out["resumed"] >= 1 and out["measured"] >= 1
    stats = await session.get(MicroAppStats, env.id, populate_existing=True)
    assert stats.db_tables == 1 and stats.db_sampled_at is not None
    done = await jobs.microapp_process_operation({}, "op_stuck1")
    assert done["outcome"] == "failed"
    await jobs.microapp_control_retry({}, "op_stuck1")


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_control_with_an_unreachable_broker_stays_draining(client, session, monkeypatch):
    owner = await mk_user(session)
    await session.commit()
    op, env = await _published(client, session, owner)
    from app.services.micro_applications import control

    async def down(*a, **k):
        raise OSError("broker down")

    monkeypatch.setattr(control, "broker_admin", down)
    await login_as(client, owner)
    r = await client.post(
        f"/api/micro-applications/{op['asset_id']}/control",
        json={
            "action": "suspend",
            "expected_generation": env.control_generation,
            "idempotency_key": "ctl-down-001",
        },
        headers=origin(),
    )
    assert (
        r.status_code == 202 and r.json()["status"] == "running" and r.json()["step"] == "draining"
    )
    await session.refresh(env)
    assert env.desired_state == "suspended"
    replay = await client.post(
        f"/api/micro-applications/{op['asset_id']}/control",
        json={
            "action": "suspend",
            "expected_generation": env.control_generation - 1,
            "idempotency_key": "ctl-down-001",
        },
        headers=origin(),
    )
    assert replay.json()["operation_id"] == r.json()["operation_id"]
    reused = await client.post(
        f"/api/micro-applications/{op['asset_id']}/control",
        json={"action": "enable", "expected_generation": 0, "idempotency_key": "ctl-down-001"},
        headers=origin(),
    )
    assert reused.json()["code"] == "idempotency_key_reused"
    bad = await client.post(
        f"/api/micro-applications/{op['asset_id']}/control",
        json={
            "action": "explode",
            "expected_generation": env.control_generation,
            "idempotency_key": "ctl-bad-0001",
        },
        headers=origin(),
    )
    assert bad.json()["code"] == "invalid_action"


def test_contract_template_and_ddl_literals():
    from app.services.micro_applications import contract, ddl

    built = contract.build(get_settings())
    paths = [f["path"] for f in built["sections"]["template"]["files"]]
    assert "microapp.json" in paths and "handlers/toggle-pin.mjs" in paths
    assert ddl.literal({"type": "boolean"}, True) == "TRUE"
    assert ddl.literal({"type": "integer"}, 5) == "5"
    assert ddl.literal({"type": "decimal"}, "1.50") == "'1.50'::numeric"
    assert ddl.literal({"type": "date"}, "2026-01-02") == "'2026-01-02'::date"
    assert ddl.literal({"type": "uuid"}, "00000000-0000-0000-0000-000000000000").endswith("::uuid")
    assert ddl.literal({"type": "timestamptz"}, "2026-01-02T00:00:00Z").endswith("::timestamptz")
    for f, v in (
        ({"type": "boolean"}, "x"),
        ({"type": "integer"}, True),
        ({"type": "string"}, "a\x00"),
    ):
        with pytest.raises(ValueError):
            ddl.literal(f, v)
    cols = {
        "a": {"type": "string", "maxLength": 9, "minLength": 1, "required": True, "default": "x"},
        "b": {"type": "integer", "minimum": 0, "maximum": 9},
        "c": {"type": "decimal", "precision": 5, "scale": 2, "minimum": "0", "maximum": "9.5"},
        "d": {"type": "enum", "values": ["x", "y"]},
        "e": {"type": "json", "maxBytes": 100},
        "f": {"type": "uuid", "references": {"collection": "t"}},
        "g": {"type": "timestamptz"},
        "h": {"type": "date"},
        "i": {"type": "boolean", "default": False},
    }
    stmts, fks = ddl.create_table_sql(
        "a_" + "0" * 32, "t", {"fields": cols, "indexes": [{"fields": ["a"], "unique": True}]}
    )
    assert (
        "CHECK (char_length" in stmts[0] and "UNIQUE INDEX" in stmts[1] and "FOREIGN KEY" in fks[0]
    )
    old = {"t": {"fields": {"a": cols["a"]}, "indexes": [{"fields": ["a"]}]}}
    new = {
        "t": {
            "fields": {"a": cols["a"], "z": {"type": "string", "maxLength": 3, "required": True}},
            "indexes": [],
        },
        "u": {"fields": {}},
    }
    delta = ddl.diff("a_" + "0" * 32, old, new)
    reasons = " ".join(d["reason"] for d in delta.destructive)
    assert (
        "needs a default" in reasons
        and "cannot be removed" in reasons
        and delta.collections_added == ["u"]
    )


def test_runtime_state_follows_the_live_broker():
    from datetime import UTC, datetime, timedelta

    from app.models import MicroAppEnvironment
    from app.services.micro_applications.status import _runtime

    env = MicroAppEnvironment(
        desired_state="enabled", updated_at=datetime.now(UTC) - timedelta(hours=1)
    )
    fresh = MicroAppStats(
        runtime_state="ready",
        runtime_sampled_at=datetime.now(UTC),
        broker_incarnation="b1",
        inflight=0,
        queued=0,
        open_connections=2,
    )
    assert _runtime(env, fresh, "b1")["state"] == "ready"
    # A newer broker never served the app: nothing runs for it.
    assert _runtime(env, fresh, "b2")["state"] == "sleeping"
    stale = MicroAppStats(
        runtime_state="ready",
        runtime_sampled_at=datetime.now(UTC) - timedelta(minutes=5),
        broker_incarnation="b1",
        inflight=0,
        queued=0,
        open_connections=0,
    )
    # No broker heartbeat and an old sample: honestly unknown.
    assert _runtime(env, stale, None)["state"] == "unknown"
    env.desired_state = "suspended"
    assert _runtime(env, fresh, "b1")["state"] == "suspended"


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_share_links_open_the_app_with_the_links_permissions(client, session):
    from urllib.parse import parse_qs, urlparse

    from app.models import AssetShare
    from app.services.micro_applications import runtime

    owner = await mk_user(session)
    editor = await mk_user(session)
    await session.commit()
    op, env = await _published(client, session, owner)
    aid = op["asset_id"]
    session.add(AssetShare(asset_id=uuid.UUID(aid), user_id=editor.id, role="editor"))
    await session.commit()
    host = f"{env.host_name}.{get_settings().microapps_app_host_suffix}"
    legacy = f"a-{env.asset_hex}-prod.{get_settings().microapps_app_host_suffix}"

    await login_as(client, editor)
    r = await client.post(
        f"/api/assets/{aid}/shares",
        json={"mode": "public", "app_permissions": ["requests.read"]},
        headers=origin(),
    )
    assert r.json()["code"] == "share_forbidden"

    await login_as(client, owner)
    for perms, code in ((None, "app_permissions_invalid"), (["nope.x"], "app_permissions_invalid")):
        r = await client.post(
            f"/api/assets/{aid}/shares",
            json={"mode": "public", "app_permissions": perms},
            headers=origin(),
        )
        assert r.json()["code"] == code
    link = (
        await client.post(
            f"/api/assets/{aid}/shares",
            json={"mode": "public", "app_permissions": ["requests.read", "requests.create"]},
            headers=origin(),
        )
    ).json()
    assert link["app_permissions"] == ["requests.create", "requests.read"]
    pw_link = (
        await client.post(
            f"/api/assets/{aid}/shares",
            json={
                "mode": "password",
                "password": "Long-enough-pass-42",
                "app_permissions": ["requests.read"],
            },
            headers=origin(),
        )
    ).json()

    client.cookies.clear()
    info = (await client.get(f"/api/share/{link['token']}/info")).json()
    assert info["kind"] == "micro_application"
    assert info["app_launch_url"] == f"https://{host}/__ics/share?token={link['token']}"
    r = await client.get(
        f"/api/share/{link['token']}/launch?host={host}&state=st1", follow_redirects=False
    )
    assert r.status_code == 302 and "/__ics/callback?code=" in r.headers["location"]
    code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]
    ex = await runtime.exchange_launch_code(code, host, "st1")
    assert ex["share_id"] == link["id"] and ex["user_id"] is None
    # A visitor who still has the long address goes through the same gate.
    old = await client.get(
        f"/api/share/{link['token']}/launch?host={legacy}&state=st1", follow_redirects=False
    )
    old_ex = await runtime.exchange_launch_code(
        parse_qs(urlparse(old.headers["location"]).query)["code"][0], legacy, "st1"
    )
    assert old_ex["share_id"] == link["id"] and old_ex["asset_hex"] == env.asset_hex
    wrong_host = await client.get(
        f"/api/share/{link['token']}/launch?host=a-{'0' * 32}-prod.x&state=st1",
        follow_redirects=False,
    )
    assert wrong_host.status_code == 404
    # The link of one app never yields a code for another app's host.
    _, other_env = await _published(client, session, owner)
    other_host = f"{other_env.host_name}.{get_settings().microapps_app_host_suffix}"
    crossed = await client.get(
        f"/api/share/{link['token']}/launch?host={other_host}&state=st1", follow_redirects=False
    )
    assert crossed.status_code == 404
    gated = await client.get(
        f"/api/share/{pw_link['token']}/launch?host={host}&state=st2", follow_redirects=False
    )
    assert gated.status_code == 302 and gated.headers["location"] == f"/s/{pw_link['token']}"

    # A member who may use the app enters as themselves, not counted.
    await login_as(client, owner)
    own = await client.get(
        f"/api/share/{link['token']}/launch?host={host}&state=st3", follow_redirects=False
    )
    own_code = parse_qs(urlparse(own.headers["location"]).query)["code"][0]
    own_ex = await runtime.exchange_launch_code(own_code, host, "st3")
    assert own_ex["user_id"] == str(owner.id) and own_ex["share_id"] is None
    shares = (await client.get(f"/api/assets/{aid}/shares")).json()
    # Two visitor launches (short and long host); the member's is not counted.
    assert next(s for s in shares if s["id"] == link["id"])["view_count"] == 2
    client.cookies.clear()

    visitor = str(uuid.uuid4())
    auth = (
        await client.post(
            "/api/internal/microapps/authorize",
            headers=SVC,
            json={
                "asset": env.asset_hex,
                "environment": "prod",
                "user_id": visitor,
                "share_id": link["id"],
            },
        )
    ).json()
    assert (
        auth["app_use"]
        and auth["user"]["id"] == visitor
        and auth["user"]["guest"] is True
        and auth["user"]["display_name"] is None
        and auth["permissions"] == ["requests.create", "requests.read"]
    )

    await login_as(client, owner)
    assert (await client.delete(f"/api/shares/{link['id']}", headers=origin())).status_code == 204
    after = (
        await client.post(
            "/api/internal/microapps/authorize",
            headers=SVC,
            json={
                "asset": env.asset_hex,
                "environment": "prod",
                "user_id": visitor,
                "share_id": link["id"],
            },
        )
    ).json()
    assert after["app_use"] is False and after["permissions"] == []
    client.cookies.clear()
    gone = await client.get(
        f"/api/share/{link['token']}/launch?host={host}&state=st4", follow_redirects=False
    )
    assert gone.status_code == 302 and gone.headers["location"] == f"/s/{link['token']}"


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_share_launch_without_access_ends_on_the_share_page(client, session, monkeypatch):
    owner = await mk_user(session)
    outsider = await mk_user(session, email=f"out+{uuid.uuid4().hex[:8]}@outside.example")
    await session.commit()
    op, env = await _published(client, session, owner)
    host = f"a-{env.asset_hex}-prod.{get_settings().microapps_app_host_suffix}"
    await login_as(client, owner)
    token = (
        await client.post(
            f"/api/assets/{op['asset_id']}/shares",
            json={"mode": "org_sso", "app_permissions": ["requests.read"]},
            headers=origin(),
        )
    ).json()["token"]
    launch = f"/api/share/{token}/launch?host={host}&state=st1"

    client.cookies.clear()
    anon = await client.get(launch, follow_redirects=False)
    assert anon.headers["location"].startswith("/#login?next=")
    # Signed in outside the allowed domain: no way in, and no redirect back
    # to the sign-in page (that would loop through the app origin).
    await login_as(client, outsider)
    out = await client.get(launch, follow_redirects=False)
    assert out.status_code == 302 and out.headers["location"] == f"/s/{token}"
    assert (await client.get(f"/api/share/{token}/info")).json()["has_access"] is False

    monkeypatch.setattr(get_settings(), "microapps_enabled", False)
    off = await client.get(launch, follow_redirects=False)
    assert off.status_code == 404 and off.json()["code"] == "microapps_disabled"
    assert "app_launch_url" not in (await client.get(f"/api/share/{token}/info")).json()


async def test_document_links_take_no_app_permissions(client, session):
    from tests.conftest import mk_asset

    user = await mk_user(session)
    asset = await mk_asset(session, user)
    await session.commit()
    await login_as(client, user)
    r = await client.post(
        f"/api/assets/{asset.id}/shares",
        json={"mode": "org_sso", "app_permissions": ["x.y"]},
        headers=origin(),
    )
    assert r.json()["code"] == "app_permissions_not_applicable"


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_owner_data_limit_marks_every_app_of_the_owner_full(client, session):
    owner = await mk_user(session)
    await session.commit()
    _, env = await _published(client, session, owner)

    from app import quota as quota_svc

    async def quota():
        # The worker publishes the full owners after each measurement.
        await quota_svc.refresh_full_owners(session)
        r = await client.post(
            "/api/internal/microapps/authorize",
            headers=SVC,
            json={"asset": env.asset_hex, "environment": "prod", "user_id": str(owner.id)},
        )
        return r.json()["data_quota"]

    stats = await session.get(MicroAppStats, env.id) or MicroAppStats(environment_id=env.id)
    stats.db_bytes = 3 * 1024**2
    session.add(stats)
    owner.microapp_data_max_bytes = 4 * 1024**2
    await session.commit()
    assert await quota() == {"exceeded": False}
    owner.microapp_data_max_bytes = 3 * 1024**2
    await session.commit()
    assert (await quota())["exceeded"] is True


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_access_is_set_declaratively_for_a_person(client, session):
    from app.models import AssetShare

    owner = await mk_user(session)
    bob = await mk_user(session)
    stranger = await mk_user(session)
    await session.commit()
    op, env = await _published(client, session, owner)
    url = f"/api/micro-applications/{op['asset_id']}/access"

    view = (await client.get(url, headers=bearer(owner))).json()
    catalog = {p["permission"]: p["allows"] for p in view["permissions"]}
    assert catalog["requests.read"] and "app.control" in catalog
    assert [p["access"] for p in view["people"]] == ["owner"]

    async def put(body, who=owner):
        return await client.put(url, json=body, headers=bearer(who))

    want = {"user_email": bob.email, "permissions": ["requests.read", "requests.create"]}
    first = (await put({**want, "can_open": True})).json()
    assert first["added"] == ["requests.create", "requests.read"]
    assert first["open_change"] == "viewer_share_added"
    assert first["person"]["can_open"] and first["person"]["access"] == "viewer"
    again = (await put({**want, "can_open": True})).json()
    assert again["added"] == again["removed"] == [] and again["open_change"] is None

    auth = (
        await client.post(
            "/api/internal/microapps/authorize",
            headers=SVC,
            json={"asset": env.asset_hex, "environment": "prod", "user_id": str(bob.id)},
        )
    ).json()
    assert auth["permissions"] == ["requests.create", "requests.read"]

    narrowed = (await put({"user_email": bob.email, "permissions": ["requests.read"]})).json()
    assert narrowed["removed"] == ["requests.create"] and narrowed["open_change"] is None
    gone = (await put({"user_email": bob.email, "permissions": [], "can_open": False})).json()
    assert gone["removed"] == ["requests.read"] and gone["open_change"] == "viewer_share_removed"
    assert gone["person"]["can_open"] is False

    bad = await put({"user_email": bob.email, "permissions": ["requests.fly"]})
    assert bad.status_code == 400 and "requests.read" in bad.json()["allowed"]
    nobody = await put({"user_email": "nobody@example.com", "permissions": []})
    assert nobody.json()["code"] == "user_not_found"
    both = await put({"user_email": bob.email, "project_id": str(uuid.uuid4())})
    assert both.json()["code"] == "principal_required"
    await put({**want, "can_open": True})
    session.add(AssetShare(asset_id=uuid.UUID(op["asset_id"]), user_id=stranger.id, role="editor"))
    await session.commit()
    kept = (await put({"user_email": stranger.email, "permissions": [], "can_open": False})).json()
    assert kept["open_change"] is None and kept["still_opens_via"] == "editor"
    denied = await put({"user_email": stranger.email, "permissions": []}, who=bob)
    assert denied.json()["code"] == "manage_permission_required"


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_an_app_reads_as_a_document_with_the_readers_records(client, session, monkeypatch):
    import httpx

    from app.services.micro_applications import document

    owner = await mk_user(session)
    outsider = await mk_user(session)
    await session.commit()
    op, _ = await _published(client, session, owner)
    url = f"/api/micro-applications/{op['asset_id']}"
    await client.put(
        f"{url}/access",
        json={"user_email": owner.email, "permissions": ["requests.read"]},
        headers=bearer(owner),
    )
    sent: list[dict] = []

    async def fake_broker(settings, method, path, body=None, timeout=15.0):
        sent.append({"path": path, **body})
        return {
            "collections": [
                {
                    "name": "requests",
                    "readable": True,
                    "items": [
                        {"id": "r1", "created_by": str(owner.id), "title": "Laptop | dock"},
                        {"id": "r2", "created_by": str(uuid.uuid4()), "title": "Visitor"},
                    ],
                    "next_cursor": "c2",
                }
            ]
        }

    monkeypatch.setattr(document, "broker_admin", fake_broker)
    doc = (await client.get(f"{url}/document", headers=bearer(owner))).json()
    assert sent[0]["user_id"] == str(owner.id) and sent[0]["path"].endswith("/prod/export")
    md = doc["markdown"]
    assert "## Permissions" in md and "`requests.read`" in md and "## Data model" in md
    author = owner.display_name or owner.email.split("@")[0]
    assert f"| r1 | {author} | Laptop \\| dock |" in md and "cursor=c2" in md
    assert "| r2 | link visitor | Visitor |" in md and str(owner.id) not in md
    assert "<table>" in doc["html"] and doc["collections"][0]["next_cursor"] == "c2"
    more = (
        await client.get(f"{url}/document?collection=requests&cursor=c2", headers=bearer(owner))
    ).json()
    assert sent[-1]["collection"] == "requests" and sent[-1]["cursor"] == "c2"
    assert more["markdown"].startswith("### requests (continued)")

    async def down(*a, **k):
        raise httpx.ConnectError("no broker")

    monkeypatch.setattr(document, "broker_admin", down)
    offline = (await client.get(f"{url}/document", headers=bearer(owner))).json()
    assert (
        offline["error"] == "broker_unavailable" and "Data unavailable now" in offline["markdown"]
    )
    hidden = await client.get(f"{url}/document", headers=bearer(outsider))
    assert hidden.status_code == 404


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_roles_give_their_permissions_to_people_projects_and_links(client, session):
    import json

    from app.models import Project, ProjectMember
    from app.slug import generate_slug
    from app.util import now as utc_now
    from tests.test_microapps import _payload

    owner = await mk_user(session)
    bob = await mk_user(session)
    carol = await mk_user(session)
    await session.commit()
    op, env = await _published(client, session, owner)
    aid = op["asset_id"]
    url = f"/api/micro-applications/{aid}/access"

    view = (await client.get(url, headers=bearer(owner))).json()
    assert [(r["role"], r["label"]) for r in view["roles"]] == [
        ("employee", "Employee"),
        ("reviewer", "Reviewer"),
    ]
    labels = {p["permission"]: p["label"] for p in view["permissions"]}
    assert labels["requests.approve"] == "Approve other people's requests"

    async def put(body):
        return await client.put(url, json=body, headers=bearer(owner))

    async def authorize(user_id, share_id=None):
        body = {"asset": env.asset_hex, "environment": "prod", "user_id": user_id}
        if share_id:
            body["share_id"] = share_id
        return (
            await client.post("/api/internal/microapps/authorize", headers=SVC, json=body)
        ).json()

    first = (await put({"user_email": bob.email, "roles": ["employee"], "can_open": True})).json()
    assert first["roles_added"] == ["employee"] and first["added"] == []
    assert first["person"]["roles"] == ["employee"] and first["person"]["permissions"] == []
    assert first["person"]["effective_permissions"] == [
        "requests.create",
        "requests.delete",
        "requests.edit",
        "requests.read",
    ]
    auth = await authorize(str(bob.id))
    assert auth["roles"] == ["employee"] and "requests.approve" not in auth["permissions"]
    again = (await put({"user_email": bob.email, "roles": ["employee"], "can_open": True})).json()
    assert again["roles_added"] == again["roles_removed"] == [] and again["open_change"] is None

    bad = await put({"user_email": bob.email, "roles": ["boss"]})
    assert bad.json()["code"] == "role_unknown" and bad.json()["allowed"] == [
        "employee",
        "reviewer",
    ]

    # A role held through a project adds to the person's own.
    project = Project(slug=generate_slug(), name="Reviewers")
    session.add(project)
    await session.flush()
    session.add(
        ProjectMember(project_id=project.id, user_id=bob.id, role="viewer", accepted_at=utc_now())
    )
    await session.commit()
    team = (await put({"project_id": str(project.id), "roles": ["reviewer"]})).json()
    assert team["project"]["roles"] == ["reviewer"]
    assert team["project"]["effective_permissions"] == ["requests.approve", "requests.read"]
    bob_now = next(
        p
        for p in (await client.get(url, headers=bearer(owner))).json()["people"]
        if p["email"] == bob.email
    )
    assert (
        bob_now["roles"] == ["employee"] and "requests.approve" in bob_now["effective_permissions"]
    )
    assert sorted((await authorize(str(bob.id)))["roles"]) == ["employee", "reviewer"]

    # Single permissions stay possible beside roles.
    mixed = (
        await put(
            {"user_email": carol.email, "roles": ["reviewer"], "permissions": ["requests.read"]}
        )
    ).json()
    assert mixed["person"]["roles"] == ["reviewer"]
    assert mixed["person"]["permissions"] == ["requests.read"]

    # A link may give roles; the visitor gets what the role defines.
    await login_as(client, owner)
    for body in ({"app_roles": ["boss"]}, {"app_roles": [], "app_permissions": []}):
        r = await client.post(
            f"/api/assets/{aid}/shares", json={"mode": "public", **body}, headers=origin()
        )
        assert r.json()["code"] == "app_permissions_invalid"
        assert r.json()["allowed_roles"] == ["employee", "reviewer"]
    link = (
        await client.post(
            f"/api/assets/{aid}/shares",
            json={"mode": "public", "app_roles": ["reviewer"]},
            headers=origin(),
        )
    ).json()
    assert link["app_roles"] == ["reviewer"] and link["app_permissions"] == []
    visitor = await authorize(str(uuid.uuid4()), link["id"])
    assert visitor["roles"] == ["reviewer"] and visitor["permissions"] == [
        "requests.approve",
        "requests.read",
    ]
    client.cookies.clear()

    doc = (await client.get(f"/api/micro-applications/{aid}/document", headers=bearer(bob))).json()
    assert "## Roles" in doc["markdown"] and "| `employee` | Employee |" in doc["markdown"]
    assert "| your roles | `employee`, `reviewer` |" in doc["markdown"]

    # A release that drops a role people hold says so in its plan.
    files = _payload(EXAMPLES / "requests")
    m = next(f for f in files if f["path"] == "microapp.json")
    manifest = json.loads(m["content_text"])
    # Every permission needs a role: approval moves to the employees.
    manifest["roles"]["employee"]["permissions"].append("requests.approve")
    del manifest["roles"]["reviewer"]
    m["content_text"] = json.dumps(manifest)
    plan = (
        await client.post(
            "/api/micro-applications/plans",
            json={"files": files, "asset_id": aid},
            headers=bearer(owner),
        )
    ).json()
    orphaned = [w for w in plan["validation"]["warnings"] if w["code"] == "grant_orphaned"]
    assert [w["pointer"] for w in orphaned] == ["/roles"]
    assert "role:reviewer" in orphaned[0]["message"]


@needs_pg
async def test_seed_rows_fill_a_new_collection_once(client, session, apps_db):  # noqa: F811
    import asyncpg

    from tests.test_microapps import TEMPLATE, _payload

    owner = await mk_user(session)
    await session.commit()
    plan, r = await _plan_and_apply(client, owner, root=TEMPLATE, key="k-seed-0001")
    assert plan["database"]["seed_rows"] == {"notes": 1} and plan["document_view"] == "document"
    op = r.json()
    assert await _publish(session, op["operation_id"]) == "succeeded"
    hex_ = uuid.UUID(op["asset_id"]).hex
    conn = await asyncpg.connect(apps_db)
    try:
        # The provisioner reads an app's tables only as the app's owner role.
        await conn.execute(f'SET ROLE "ma_{hex_}_owner"')
        rows = await conn.fetch(f'SELECT text, pinned, created_by FROM "a_{hex_}".notes')
    finally:
        await conn.close()
    assert [(x["pinned"], x["created_by"]) for x in rows] == [(True, owner.id)]
    assert rows[0]["text"].startswith("Welcome")

    # The collection exists now: a new release brings no rows twice.
    again = (
        await client.post(
            "/api/micro-applications/plans",
            json={"files": _payload(TEMPLATE), "asset_id": op["asset_id"]},
            headers=bearer(owner),
        )
    ).json()
    assert again["database"]["seed_rows"] == {}
    assert "seed_not_applied" in {w["code"] for w in again["validation"]["warnings"]}


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_an_app_with_a_document_view_reads_as_the_app_renders_it(
    client, session, monkeypatch
):
    from app.services.micro_applications import document
    from tests.test_microapps import TEMPLATE

    owner = await mk_user(session)
    await session.commit()
    _, r = await _plan_and_apply(client, owner, root=TEMPLATE, key="k-docview-01")
    op = r.json()
    assert await _publish(session, op["operation_id"]) == "succeeded"
    url = f"/api/micro-applications/{op['asset_id']}"
    await client.put(
        f"{url}/access",
        json={"user_email": owner.email, "roles": ["author"]},
        headers=bearer(owner),
    )
    sent: list[dict] = []
    view: dict = {"markdown": "# Notes\n\n- 📌 Welcome\n\n````\n```\n# not a heading\n````"}

    async def fake_broker(settings, method, path, body=None, timeout=15.0):
        assert path.endswith("/export")
        sent.append(body)
        out = {"collections": [{"name": "notes", "readable": True, "items": []}]}
        return {**out, "document": view} if body["document"] else out

    monkeypatch.setattr(document, "broker_admin", fake_broker)
    doc = (await client.get(f"{url}/document", headers=bearer(owner))).json()
    md = doc["markdown"]
    assert md.index("## App view") < md.index("## Permissions") < md.index("## Data model")
    # The app's headings go under ours; code blocks (a longer fence holding
    # a shorter one) stay as written.
    assert "### Notes" in md and "- 📌 Welcome" in md and "\n# not a heading\n" in md
    assert doc["app_view"] == {"endpoint": "document", "error": None}
    # One broker call brings the records and the view.
    assert len(sent) == 1 and sent[0]["document"] is True
    # Paging one collection does not render the view again.
    sent.clear()
    await client.get(f"{url}/document?collection=notes", headers=bearer(owner))
    assert sent[0]["document"] is False
    # The asset page's Data tab shows the view too.
    tab = (await client.get(f"{url}/document?overview=false", headers=bearer(owner))).json()
    assert "## App view" in tab["markdown"] and "## Permissions" not in tab["markdown"]
    # An agent slices the document like a file and skips the HTML.
    part = (
        await client.get(f"{url}/document?max_lines=3&html=false", headers=bearer(owner))
    ).json()
    assert part["returned_range"] == [1, 3] and part["total_lines"] > 3 and "html" not in part
    assert part["markdown"].count("\n") == 2 and part["slug"] and part["version"] == 1

    # A failing view reports its code; the data still comes.
    view = {"error": "document_view_failed"}
    broken = (await client.get(f"{url}/document", headers=bearer(owner))).json()
    assert "App view unavailable now (`document_view_failed`)" in broken["markdown"]
    assert broken["app_view"]["error"] == "document_view_failed"
    assert "## Data" in broken["markdown"]

    # The broker refuses the view without its permission; ICS names it.
    view = {"error": "forbidden"}
    denied = (await client.get(f"{url}/document", headers=bearer(owner))).json()
    assert "Not readable for you (needs `notes.read`)" in denied["markdown"]
    assert denied["app_view"]["error"] == "forbidden"


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_publishers_compare_package_versions_users_do_not(client, session):
    import json

    from tests.test_microapps import _payload

    owner = await mk_user(session)
    bob = await mk_user(session)
    await session.commit()
    op, _ = await _published(client, session, owner)
    aid = op["asset_id"]
    await client.put(
        f"/api/micro-applications/{aid}/access",
        json={"user_email": bob.email, "roles": ["employee"], "can_open": True},
        headers=bearer(owner),
    )

    # Release 2: reviewers export, a handler changes.
    files = _payload(EXAMPLES / "requests")
    m = next(f for f in files if f["path"] == "microapp.json")
    manifest = json.loads(m["content_text"])
    manifest["permissions"]["requests.export"] = {"label": "Eksport"}
    manifest["roles"]["reviewer"]["permissions"].append("requests.export")
    m["content_text"] = json.dumps(manifest)
    h = next(f for f in files if f["path"] == "handlers/document.mjs")
    h["content_text"] += "\n// v2\n"
    r = await client.post(
        "/api/micro-applications/plans",
        json={"files": files, "asset_id": aid},
        headers=bearer(owner),
    )
    plan = r.json()
    # The plan says what the release changes for the people using the app.
    assert {(c["area"], c["name"], c["change"]) for c in plan["app_changes"]} == {
        ("permission", "requests.export", "added"),
        ("role", "reviewer", "changed"),
    }
    r = await client.post(
        f"/api/micro-applications/plans/{plan['plan_id']}/apply",
        json={
            "digest": plan["release_digest"],
            "expected_generation": plan["expected_generation"],
            "idempotency_key": f"k-{uuid.uuid4().hex[:12]}",
        },
        headers=bearer(owner),
    )
    assert await _publish(session, r.json()["operation_id"]) == "succeeded"

    versions = await client.get(f"/api/assets/{aid}/versions", headers=bearer(owner))
    assert [v["version"] for v in versions.json()] == [2, 1]
    diff = (await client.get(f"/api/assets/{aid}/versions/1/diff/2", headers=bearer(owner))).json()
    assert {f["path"]: f["change"] for f in diff["files"]} == {
        "handlers/document.mjs": "modified",
        "microapp.json": "modified",
    }
    assert {
        "area": "role",
        "name": "reviewer",
        "change": "changed",
        "detail": "+requests.export",
    } in diff["app_changes"]
    one = await client.get(
        f"/api/assets/{aid}/versions/1/diff/2?path=handlers/document.mjs", headers=bearer(owner)
    )
    assert "+// v2" in one.json()["diff"]

    # Using the app gives no right to its sources or their history.
    for path in (f"/api/assets/{aid}/versions", f"/api/assets/{aid}/versions/1/diff/2"):
        denied = await client.get(path, headers=bearer(bob))
        assert denied.status_code == 403 and denied.json()["code"] == "microapp_source_restricted"


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_link_in_the_app_address_is_checked_and_kept_past_the_gate(client, session):
    """`ics_share` of a copied app address: which live link of this app it
    names, and the app page surviving the share page's gate."""
    from urllib.parse import quote

    owner = await mk_user(session)
    await session.commit()
    op, env = await _published(client, session, owner)
    _, other_env = await _published(client, session, owner)
    await login_as(client, owner)

    async def link(asset_id: str, **body) -> dict:
        r = await client.post(
            f"/api/assets/{asset_id}/shares",
            json={"mode": "public", "app_permissions": ["requests.read"], **body},
            headers=origin(),
        )
        return r.json()

    mine = await link(op["asset_id"])
    foreign = await link(str(other_env.asset_id))
    gated = await link(op["asset_id"], mode="password", password="Long-enough-pass-42")

    async def named(token: str) -> dict:
        r = await client.post(
            "/api/internal/microapps/authorize",
            headers=SVC,
            json={"asset": env.asset_hex, "environment": "prod", "share_token": token},
        )
        return r.json()

    assert (await named(mine["token"]))["share_token_id"] == mine["id"]
    assert (await named(foreign["token"]))["share_token_id"] is None
    assert (await named("Z" * 43))["share_token_id"] is None
    plain = await named(mine["token"])
    assert plain["share_context"] is True
    assert (await client.delete(f"/api/shares/{mine['id']}", headers=origin())).status_code == 204
    assert (await named(mine["token"]))["share_token_id"] is None

    script = await client.get("/api/internal/microapps/share-context.js", headers=SVC)
    assert script.status_code == 200 and b"ics_share" in script.content

    client.cookies.clear()
    host = f"{env.host_name}.{get_settings().microapps_app_host_suffix}"
    to = "board?tab=2"
    r = await client.get(
        f"/api/share/{gated['token']}/launch",
        params={"host": host, "state": "st1", "to": to},
        follow_redirects=False,
    )
    assert r.headers["location"] == f"/s/{gated['token']}?to={quote(to, safe='')}"
    bad = await client.get(
        f"/api/share/{gated['token']}/launch",
        params={"host": host, "state": "st1", "to": "//evil.example/"},
        follow_redirects=False,
    )
    assert bad.headers["location"] == f"/s/{gated['token']}"
