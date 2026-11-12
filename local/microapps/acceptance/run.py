"""Acceptance run of the local micro-application PoC.

Needs `scripts/microapps-local.sh up` and `seed` (both pilots published
through local MCP, shared and granted). Every check runs against the real
stack: the local ICS-MCP checkout over stdio, a headless Chromium on the
app origins, Docker restarts of the shared services and the publication
fault hooks of the local profile. Results go to the console and to
.microapps-local/acceptance-report.json; a failed check fails the run.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import subprocess
import sys
import time
import traceback
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
import browser as B  # noqa: E402
import localenv as L  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

APPS = json.loads((L.STATE / "apps.json").read_text())
# The origin follows the current suffix, not the URL a past seed stored.
for _app in APPS.values():
    _app["app_url"] = f"https://a-{uuid.UUID(_app['asset_id']).hex}-prod.{L.APP_SUFFIX}/"
REQ, EQ = APPS["requests"], APPS["equipment"]
RESULTS: list[dict[str, Any]] = []
SHOTS = L.STATE / "screenshots"
SHOTS.mkdir(exist_ok=True)


def check(name: str, ok: bool, detail: Any = None) -> None:
    RESULTS.append({"check": name, "ok": bool(ok), "detail": detail})
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail is not None and not ok else ""))


def section(title: str) -> None:
    print(f"\n== {title}")


def compose(*args: str) -> str:
    out = subprocess.run([str(L.ROOT / "scripts" / "microapps-local.sh"), "compose", *args],
                         capture_output=True, text=True, check=True)
    return out.stdout


def redis_set(key: str, value: str) -> None:
    compose("exec", "-T", "redis", "redis-cli", "SET", key, value, "EX", "600")


def wait_ready(url: str = f"{L.BASE_URL}/readyz", seconds: int = 90) -> None:
    import httpx

    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            if httpx.get(url, verify=L.ssl_context(), timeout=3).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise TimeoutError(url)


# ---------- browser helpers (window.ics on the app origin) ----------

JS_CALL = """async ([method, path, opts]) => {
  try { return { ok: true, data: await ics.call(method, path, opts || {}) }; }
  catch (e) { return { ok: false, status: e.status, code: e.code, field: e.field }; }
}"""
JS_COLL = """async ([name, op, args]) => {
  try { const c = ics.collection(name); return { ok: true, data: await c[op](...args) }; }
  catch (e) { return { ok: false, status: e.status, code: e.code, field: e.field }; }
}"""
JS_RAW = """async ([method, path, body, headers]) => {
  const s = await ics.session();
  const h = { "x-ics-csrf": s.csrfToken, "x-ics-release": s.app.release, "x-ics-data-generation": String(s.app.dataGeneration), ...headers };
  if (body !== null) h["content-type"] = "application/json";
  const r = await fetch(path, { method, headers: h, body: body === null ? undefined : JSON.stringify(body) });
  let data = null; try { data = await r.json(); } catch {}
  return { status: r.status, data, replayed: r.headers.get("idempotent-replayed") };
}"""


def call(page: Any, method: str, path: str, **opts: Any) -> dict[str, Any]:
    return page.evaluate(JS_CALL, [method, path, opts])


def coll(page: Any, name: str, op: str, *args: Any) -> dict[str, Any]:
    return page.evaluate(JS_COLL, [name, op, list(args)])


def raw(page: Any, method: str, path: str, body: Any = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
    return page.evaluate(JS_RAW, [method, path, body, headers or {}])


# ---------- MCP helpers ----------


async def mcp(user: str, tool: str, args: dict[str, Any] | None = None, *, expect_error: bool = False) -> Any:
    async with L.mcp_client(user) as c:
        return await L.call(c, tool, args, expect_error=expect_error)


async def wait_op(user: str, op_id: str, seconds: int = 240) -> dict[str, Any]:
    deadline = time.time() + seconds
    async with L.mcp_client(user) as c:
        while time.time() < deadline:
            op = await L.call(c, "ics_microapp_status", {"operation_id": op_id})
            if op["terminal"]:
                return op
            await asyncio.sleep(3)
    raise TimeoutError(op_id)


async def publish(user: str, name: str, asset_id: str | None, *, fault: str | None = None) -> tuple[dict, dict]:
    async with L.mcp_client(user) as c:
        args: dict[str, Any] = {"files": L.package_files(name)}
        if asset_id:
            args["asset_id"] = asset_id
        plan = await L.call(c, "ics_microapp_plan", args)
        if fault:
            redis_set(f"microapp:fault:{plan['plan_id']}", fault)
        op = await L.call(c, "ics_microapp_apply", {"plan_id": plan["plan_id"], "digest": plan["release_digest"],
                                                    "expected_generation": plan["expected_generation"], "confirm": True})
    return plan, op


async def status(user: str, asset_id: str) -> dict[str, Any]:
    return await mcp(user, "ics_microapp_status", {"asset_id": asset_id})


# ---------- scenarios ----------


def browser_scenarios(probe_url: str) -> None:
    with sync_playwright() as p:
        br = B.launch(p)
        bob = B.login(br, "bob")
        carol = B.login(br, "carol")
        dave = B.login(br, "dave")
        alice = B.login(br, "alice")

        section("Requests app: CRUD, custom endpoint, rules")
        pb = B.open_app(bob, REQ["app_url"])
        r = coll(pb, "requests", "create", {"title": "Monitor do pracy", "description": "27 cali"})
        check("bob creates a request through generic CRUD", r["ok"] and r["data"]["revision"] == 1, r)
        rid, rev = r["data"]["id"], r["data"]["revision"]
        r = coll(pb, "requests", "update", rid, rev, {"title": "Monitor 27 cali"})
        check("bob edits his own submitted request (If-Match)", r["ok"] and r["data"]["revision"] == 2, r)
        r = coll(pb, "requests", "update", rid, rev, {"title": "stale"})
        check("a stale revision is refused with 412", not r["ok"] and r["status"] == 412, r)
        r = coll(pb, "requests", "update", rid, 2, {"status": "approved"})
        check("status cannot be set through generic CRUD (422)", not r["ok"] and r["status"] == 422, r)
        r = coll(pb, "requests", "create", {"title": "Do usunięcia"})
        r2 = coll(pb, "requests", "remove", r["data"]["id"], r["data"]["revision"])
        check("bob deletes his own request", r2["ok"], r2)
        r = call(pb, "POST", f"/v1/custom/requests/{rid}/approve", body={}, ifMatch=2)
        check("bob (no requests.approve) cannot call the approve endpoint", not r["ok"] and r["status"] == 403, r)
        # Replay records live 24 h: a fresh key and title per run, or an
        # expired key from an earlier run adds a second row.
        run = uuid.uuid4().hex[:12]
        key, title = f"replay-key-{run}", f"Idempotentny {run}"
        first = raw(pb, "POST", "/api/v1/collections/requests", {"title": title}, {"idempotency-key": key})
        again = raw(pb, "POST", "/api/v1/collections/requests", {"title": title}, {"idempotency-key": key})
        other = raw(pb, "POST", "/api/v1/collections/requests", {"title": "Inny"}, {"idempotency-key": key})
        listed = coll(pb, "requests", "list", {"limit": 200})
        same = [i for i in listed["data"]["items"] if i["title"] == title]
        check("a retried create with the same key returns the stored result, one row",
              first["status"] == 201 and again["status"] == 201 and again["replayed"] == "true"
              and again["data"]["id"] == first["data"]["id"] and len(same) == 1, (first["status"], again, len(same)))
        check("the same key with another body is a conflict", other["status"] == 409 and other["data"]["code"] == "idempotency_key_reused", other)
        pb.screenshot(path=str(SHOTS / "requests-bob.png"), full_page=True)

        pc = B.open_app(carol, REQ["app_url"])
        queue = call(pc, "GET", "/v1/custom/review-requests", query={"limit": 50})
        ids = [i["id"] for i in queue["data"]["items"]] if queue["ok"] else []
        check("carol's review queue holds bob's submitted request", rid in ids, queue)
        own = coll(pc, "requests", "create", {"title": "Wniosek Karoliny"})
        queue2 = call(pc, "GET", "/v1/custom/review-requests", query={"limit": 50})
        check("the queue never contains the reviewer's own requests", own["data"]["id"] not in [i["id"] for i in queue2["data"]["items"]], queue2)
        self_ap = call(pc, "POST", f"/v1/custom/requests/{own['data']['id']}/approve", body={}, ifMatch=1)
        check("self-approval is refused", not self_ap["ok"] and self_ap["status"] in (403, 404), self_ap)
        mine_only = coll(pc, "requests", "get", rid)
        check("carol cannot read bob's request through CRUD (own row scope)", not mine_only["ok"] and mine_only["status"] == 404, mine_only)
        ap = call(pc, "POST", f"/v1/custom/requests/{rid}/approve", body={}, ifMatch=2)
        check("carol approves bob's request through the custom endpoint", ap["ok"] and ap["data"]["status"] == "approved" and ap["data"]["revision"] == 3, ap)
        ap2 = call(pc, "POST", f"/v1/custom/requests/{rid}/approve", body={}, ifMatch=2)
        check("a second approval with the old revision changes nothing (409/412)", not ap2["ok"] and ap2["status"] in (409, 412), ap2)
        r = coll(pb, "requests", "update", rid, 3, {"title": "po zatwierdzeniu"})
        check("an approved request is no longer editable (409 invalid_state)", not r["ok"] and r["status"] == 409, r)
        pc.screenshot(path=str(SHOTS / "requests-carol.png"), full_page=True)

        pd = B.open_app(dave, REQ["app_url"])
        r = coll(pd, "requests", "list", {"limit": 10})
        check("dave (visible asset, no business permission) cannot list", not r["ok"] and r["status"] == 403, r)

        section("Equipment app: two tables in one transaction")
        pa = B.open_app(alice, EQ["app_url"])
        r = coll(pa, "equipment", "create", {"name": "Projektor Epson", "category": "projector", "quantity": 2, "available": 2, "active": True})
        check("alice adds equipment", r["ok"], r)
        eid = r["data"]["id"]
        pe = B.open_app(bob, EQ["app_url"])
        today = time.strftime("%Y-%m-%d")
        res = call(pe, "POST", "/v1/custom/reservations", body={"equipmentId": eid, "startsOn": today, "endsOn": today, "quantity": 1})
        check("bob reserves one unit (stock and reservation written together)", res["ok"] and res["data"]["available"] == 1, res)
        bad = call(pe, "POST", "/v1/custom/reservations", body={"equipmentId": eid, "startsOn": today, "endsOn": today, "quantity": 1, "note": "x" * 350})
        after = coll(pe, "equipment", "get", eid)
        check("a failure after the stock update rolls the whole request back", not bad["ok"] and after["data"]["available"] == 1, (bad, after.get("data", {}).get("available")))
        pc2 = B.open_app(carol, EQ["app_url"])
        both = pe.evaluate("""async ([eid, d]) => {
          const body = { equipmentId: eid, startsOn: d, endsOn: d, quantity: 1 };
          const r = await Promise.allSettled([ics.call("POST", "/v1/custom/reservations", { body }), ics.call("POST", "/v1/custom/reservations", { body })]);
          return r.map((x) => x.status === "fulfilled" ? 201 : x.reason.status);
        }""", [eid, today])
        final = coll(pa, "equipment", "get", eid)
        check("two concurrent bookings of the last unit: one wins, stock never negative",
              sorted(both)[0] == 201 and both.count(201) == 1 and final["data"]["available"] == 0, (both, final.get("data")))
        mine = coll(pe, "reservations", "list", {"limit": 50})
        active = [x for x in mine["data"]["items"] if x["status"] == "active"]
        cancel = call(pe, "POST", f"/v1/custom/reservations/{active[0]['id']}/cancel", body={}, ifMatch=active[0]["revision"])
        check("cancelling returns the unit to stock", cancel["ok"] and cancel["data"]["available"] == 1, cancel)
        theirs = coll(pc2, "reservations", "get", active[0]["id"])
        check("carol cannot read bob's reservation", not theirs["ok"] and theirs["status"] == 404, theirs)
        pe.screenshot(path=str(SHOTS / "equipment-bob.png"), full_page=True)

        section("Apps cannot touch the ICS session")
        names = {c["name"]: c for c in bob.cookies() if c["domain"].lstrip(".") == "ics.localhost"}
        check("the ICS session cookie carries the __Host- prefix (Secure, Path=/, no Domain)",
              "__Host-ics-session" in names and names["__Host-ics-session"]["secure"] and names["__Host-ics-session"]["path"] == "/", sorted(names))
        before = {(c["name"], c["value"]) for c in bob.cookies() if "ics.localhost" in c["domain"] and "ics-apps" not in c["domain"]}
        pb.evaluate("""() => {
          for (const d of ["ics.localhost", ".localhost"]) {
            document.cookie = `__Host-ics-session=planted; Domain=${d}; Path=/; Secure`;
            document.cookie = `session=planted; Domain=${d}; Path=/; Secure`;
          }
          document.cookie = "__Host-ics-session=planted; Path=/; Secure";
        }""")
        after = {(c["name"], c["value"]) for c in bob.cookies() if "ics.localhost" in c["domain"] and "ics-apps" not in c["domain"]}
        check("an app's script cannot plant a cookie for the ICS host (separate site)", before == after, sorted(after - before))
        ics_tab = bob.new_page()
        me = ics_tab.goto(f"{L.BASE_URL}/api/auth/me")
        check("bob is still signed in to ICS as himself", me.status == 200 and me.json().get("email") == "bob@example.com", me.status)
        ics_tab.close()

        section("A/B isolation in the browser (same user, both apps open)")
        cross = pb.evaluate("""async (url) => {
          const out = {};
          try { await fetch(url + "api/v1/collections/equipment", { credentials: "include" }); out.read = "readable"; }
          catch (e) { out.read = "blocked"; }
          try {
            const r = await fetch(url + "api/v1/collections/equipment", { method: "POST", credentials: "include", mode: "no-cors",
              headers: { "content-type": "text/plain" }, body: "{}" });
            out.write = r.type;
          } catch (e) { out.write = "blocked"; }
          return out;
        }""", EQ["app_url"])
        check("script of app A cannot read app B's API (no CORS for other origins)", cross["read"] == "blocked", cross)
        eq_count_before = len(coll(pa, "equipment", "list", {"limit": 200})["data"]["items"])
        forged = pe.evaluate("""async () => {
          const r = await fetch("/api/v1/collections/equipment", { method: "POST", headers: { "content-type": "application/json",
            "x-ics-release": "x", "x-ics-data-generation": "1", "idempotency-key": "forged-0000001" }, body: "{}" });
          return r.status; }""")
        check("a write without the session's CSRF token is refused", forged == 403, forged)
        eq_count_after = len(coll(pa, "equipment", "list", {"limit": 200})["data"]["items"])
        check("no equipment row appeared from cross-origin attempts", eq_count_after == eq_count_before, (eq_count_before, eq_count_after))
        a_cookie = next(c for c in bob.cookies() if c["name"] == "__Host-ics-app" and c["domain"].startswith(REQ["app_url"].split("//")[1].split(".")[0]))
        other_ctx = br.new_context()
        other_ctx.add_cookies([{"name": a_cookie["name"], "value": a_cookie["value"], "url": EQ["app_url"], "secure": True}])
        page = other_ctx.new_page()
        resp = page.goto(EQ["app_url"] + "api/v1/session")
        check("app A's session cookie is useless on app B's origin", resp.status == 401, resp.status)
        resp = page.goto(f"{L.BASE_URL}/api/auth/me")
        check("app session cookie does not open the main ICS API", resp.status == 401, resp.status)
        other_ctx.close()

        section("Revoking access works on an open session")
        no_read = ["requests.create", "requests.delete", "requests.edit"]

        def bob_access(**grants: list[str]) -> dict[str, Any]:
            # Sync Playwright owns this thread's event loop: run MCP in another thread.
            args = {"asset_id": REQ["asset_id"], "user_email": "bob@example.com", **grants, "confirm": True}
            with ThreadPoolExecutor(1) as pool:
                return pool.submit(lambda: asyncio.run(mcp("alice", "ics_microapp_access_set", args))).result()

        cut = bob_access(roles=[], permissions=no_read)
        check("taking bob's role and giving all but requests.read is one exact change",
              cut["roles_removed"] == ["employee"] and cut["added"] == no_read, cut)
        r = coll(pb, "requests", "list", {"limit": 5})
        check("bob's open tab loses requests.read immediately after revocation", not r["ok"] and r["status"] == 403, r)
        back = bob_access(roles=["employee"])
        check("the role back replaces the single permissions", back["roles_added"] == ["employee"] and back["removed"] == no_read, back)
        r = coll(pb, "requests", "list", {"limit": 5})
        check("re-granting restores it", r["ok"], r)

        section("Runtime limits (probe app)")
        pp = B.open_app(alice, probe_url)
        t0 = time.time()
        spin = call(pp, "GET", "/v1/custom/spin")
        took = time.time() - t0
        check("an endless loop ends with 504 execution_deadline within the budget", not spin["ok"] and spin["status"] == 504 and took < 6, (spin, round(took, 2)))
        alloc = call(pp, "GET", "/v1/custom/alloc")
        # 507 memory_limit when the guest heap limit answers first, 504
        # runner_killed when the runner's OS memory limit kills the child.
        check(f"a runaway allocation is stopped inside the runner ({alloc.get('code')})",
              not alloc["ok"] and alloc.get("code") in ("memory_limit", "runner_killed", "runner_crashed"), alloc)
        ok = coll(pb, "requests", "list", {"limit": 5})
        check("other apps keep working while the probe fails", ok["ok"], ok)
        ping = call(pp, "GET", "/v1/custom/ping")
        check("the probe itself recovers on a fresh runner process", ping["ok"], ping)
        call(pp, "GET", "/v1/custom/spin")
        breaker = call(pp, "GET", "/v1/custom/ping")
        check("repeated failures open the app's circuit breaker (503)", not breaker["ok"] and breaker["status"] == 503 and breaker["code"] == "circuit_open", breaker)

        section("Panel: micro-applications are ordinary assets")
        panel_page = alice.new_page()
        panel_page.goto(f"{L.BASE_URL}/microapps")
        panel_page.wait_for_selector("text=Rejestr wniosków", timeout=15000)
        check("the old /microapps address lands on the documents list filtered by kind",
              "f=type%3Amicro_application" in panel_page.url, panel_page.url)
        slug = panel_page.evaluate(f"async () => (await (await fetch('/api/micro-applications/{REQ['asset_id']}')).json()).slug")
        panel_page.goto(f"{L.BASE_URL}/v/{slug}?tab=data")
        panel_page.wait_for_selector("text=Data model", timeout=15000)
        panel_page.wait_for_timeout(800)
        panel_page.screenshot(path=str(SHOTS / "asset-data.png"), full_page=True)
        # Alice owns the app but holds no requests.read: model yes, records no.
        check("the asset page renders the app's data tab from the document",
              panel_page.locator("table").count() >= 1 and panel_page.locator("text=needs `requests.read`").count() + panel_page.locator("text=needs requests.read").count() >= 1)
        panel_page.goto(f"{L.BASE_URL}/v/{slug}?tab=access")
        panel_page.wait_for_selector("text=carol@example.com", timeout=15000)
        panel_page.screenshot(path=str(SHOTS / "asset-access.png"), full_page=True)
        check("the access tab lists the people of the app", panel_page.locator("text=bob@example.com").count() >= 1)
        bob_row = panel_page.locator("li", has_text="bob@example.com")
        check("bob's row shows the app's roles with his one chosen",
              bob_row.get_by_role("checkbox", name="Pracownik").is_checked()
              and not bob_row.get_by_role("checkbox", name="Recenzent").is_checked())
        check("the asset page has no upload control", panel_page.locator('input[type="file"]').count() == 0)
        # With a share link the asset page and its tabs stay on /v/<slug>: the
        # link opens the app itself, so tabs under it would land in the app.
        link = panel_page.evaluate("""async (id) => (await (await fetch(`/api/assets/${id}/shares`, {
          method: "POST", headers: { "content-type": "application/json" },
          body: JSON.stringify({ mode: "org_sso", app_roles: ["employee"] }) })).json())""", REQ["asset_id"])
        panel_page.goto(f"{L.BASE_URL}/v/{slug}")
        panel_page.wait_for_timeout(1500)
        panel_page.get_by_role("link", name="Access").first.click()
        panel_page.wait_for_timeout(1500)
        check("with a share link the asset page and its tabs stay on /v/<slug>",
              panel_page.url.startswith(f"{L.BASE_URL}/v/{slug}") and "tab=access" in panel_page.url, panel_page.url)
        panel_page.evaluate("async (id) => fetch(`/api/shares/${id}`, { method: 'DELETE' })", link["id"])
        br.close()


async def mcp_scenarios() -> str:
    section("Local MCP: contract, repeated apply, status")
    for app in (REQ, EQ):
        st = await status("alice", app["asset_id"])
        if st["desired_state"] != "enabled":
            # A previous run stopped after its suspend step: start from enabled.
            await mcp("alice", "ics_microapp_control", {"asset_id": app["asset_id"], "action": "enable",
                                                        "expected_generation": st["generation"], "confirm": True})
    who = await mcp("alice", "ics_whoami")
    check("MCP session is alice on the local ICS", who["email"] == "alice@example.com" and who["audience"].startswith(L.BASE_URL), who)
    overview = await mcp("alice", "ics_microapp_contract")
    part = await mcp("alice", "ics_microapp_contract", {"section": "manifest_schema", "part": 1})
    check("contract is served in sections under one hash", part["contract_hash"] == overview["contract_hash"] and part["parts"] >= 2, part.get("parts"))

    listing = await mcp("alice", "ics_microapp_status", {"limit": 50})
    probe = next((i for i in listing["items"] if i["title"].startswith("Sonda runtime")), None)
    if probe is None or probe["release"] is None:
        plan, op = await publish("alice", "probe", probe["asset_id"] if probe else None)
        done = await wait_op("alice", op["operation_id"])
        probe_id, probe_url = done["asset_id"], done["app_url"]
    else:
        probe_id, probe_url = probe["asset_id"], probe["app_url"]
    await mcp("alice", "ics_microapp_access_set", {
        "asset_id": probe_id, "user_email": "alice@example.com", "roles": ["tester"], "confirm": True,
    })

    async with L.mcp_client("alice") as c:
        plan = await L.call(c, "ics_microapp_plan", {"files": L.package_files("probe"), "asset_id": probe_id})
        args = {"plan_id": plan["plan_id"], "digest": plan["release_digest"], "expected_generation": plan["expected_generation"], "confirm": True}
        a1 = await L.call(c, "ics_microapp_apply", args)
        a2 = await L.call(c, "ics_microapp_apply", args)
        check("a repeated apply returns the same durable operation", a1["operation_id"] == a2["operation_id"] and a2["replayed"] is True, (a1["operation_id"], a2.get("replayed")))
        other = await L.call(c, "ics_microapp_apply", {**args, "digest": "sha256:" + "0" * 64}, expect_error=True)
        check("same key, different request: idempotency_key_reused", "idempotency_key_reused" in json.dumps(other), other)
    done = await wait_op("alice", a1["operation_id"])
    check("the repeated apply published once", done["status"] == "succeeded", done.get("error"))

    section("An agent builds a new app and hands it to people, all through MCP")
    first = await mcp("alice", "ics_microapp_contract", {"section": "template"})
    text = first["content_json"]
    for n in range(2, first["parts"] + 1):
        text += (await mcp("alice", "ics_microapp_contract", {"section": "template", "part": n}))["content_json"]
    template = json.loads(text)["files"]
    plan, op = None, None
    async with L.mcp_client("alice") as c:
        plan = await L.call(c, "ics_microapp_plan", {"files": template})
        op = await L.call(c, "ics_microapp_apply", {"plan_id": plan["plan_id"], "digest": plan["release_digest"],
                                                    "expected_generation": plan["expected_generation"], "confirm": True})
    new = await wait_op("alice", op["operation_id"])
    check("the contract template publishes as a new app", new["status"] == "succeeded", new.get("error"))
    view = await mcp("alice", "ics_microapp_access", {"asset_id": new["asset_id"]})
    catalog = {p["permission"]: p["allows"] for p in view["permissions"]}
    check("ics_microapp_access says what each permission unlocks", any("notes:" in a for a in catalog.get("notes.read", [])), catalog)
    check("ics_microapp_access lists the app's roles with labels",
          [(r["role"], r["label"]) for r in view["roles"]] == [("author", "Author"), ("reader", "Reader")], view["roles"])
    mine = await mcp("alice", "ics_microapp_access_set", {"asset_id": new["asset_id"], "user_email": "alice@example.com",
                                                         "roles": ["author"], "confirm": True})
    check("the owner gives herself the author role", mine["person"]["effective_permissions"] == ["notes.read", "notes.write"], mine)
    bob = await mcp("alice", "ics_microapp_access_set", {"asset_id": new["asset_id"], "user_email": "bob@example.com",
                                                        "roles": ["reader"], "confirm": True})
    check("one call lets bob open the app as a reader, exactly notes.read",
          bob["open_change"] == "viewer_share_added" and bob["person"]["can_open"] and bob["person"]["effective_permissions"] == ["notes.read"], bob)
    new_slug = (await status("alice", new["asset_id"]))["slug"]
    doc = await mcp("bob", "ics_asset_read", {"slug_or_id": new_slug})
    check("bob reads the app as Markdown with his role, permissions and data section",
          "| your roles | `reader` |" in doc["content"] and "`notes.read`" in doc["content"] and "## Data model" in doc["content"] and "### notes" in doc["content"], doc["content"][:400])
    own = await mcp("alice", "ics_asset_read", {"slug_or_id": new_slug})
    check("the app view comes first, with the seeded note filled in from the database",
          own["content"].index("## App view") < own["content"].index("## Roles") and "Welcome: this note came" in own["content"]
          and own.get("app_view") == {"endpoint": "document", "error": None}, own.get("app_view"))
    check("the view keeps the app's row scopes: bob does not see alice's private note",
          "No notes yet" in doc["content"] and "Welcome: this note came" not in doc["content"], doc.get("app_view"))
    # People with an app role only get the asset id from ics_microapp_status.
    by_id = await mcp("bob", "ics_asset_read", {"slug_or_id": new["asset_id"], "max_lines": 20})
    check("bob reads the app by its asset id too, sliced by max_lines",
          by_id["slug"] == new_slug and by_id.get("truncated") is True and len(by_id["content"].split("\n")) == 20, by_id.get("returned_range"))
    again = await mcp("alice", "ics_microapp_access_set", {"asset_id": new["asset_id"], "user_email": "bob@example.com",
                                                          "roles": ["reader"], "confirm": True})
    check("repeating the call changes nothing",
          again["roles_added"] == again["roles_removed"] == again["added"] == again["removed"] == [] and again["open_change"] is None, again)
    link = await mcp("alice", "ics_share_create_link", {"slug_or_id": new["asset_id"], "mode": "public",
                                                       "app_roles": ["reader"], "confirm": True})
    check("a link gives a role", link["app_roles"] == ["reader"], link)
    import httpx
    info = httpx.get(f"{L.BASE_URL}/api/share/{link['token']}/info", verify=L.ssl_context(), timeout=10).json()
    check("a public link opens the app itself, without sign-in", info["has_access"] and info["app_launch_url"].startswith(new["app_url"]), info)
    gone = await mcp("alice", "ics_microapp_access_set", {"asset_id": new["asset_id"], "user_email": "bob@example.com",
                                                         "roles": [], "can_open": False, "confirm": True})
    check("roles=[] and can_open=false remove bob completely", gone["roles_removed"] == ["reader"] and not gone["person"]["can_open"], gone)
    await mcp("alice", "ics_asset_delete", {"slug_or_id": new["asset_id"], "confirm": True})

    section("Agents read an app as each person sees it")
    views = {u: await mcp(u, "ics_asset_read", {"slug_or_id": REQ["asset_id"]}) for u in ("bob", "carol", "dave")}
    check("bob's view of the register lists his own requests, without the review queue",
          "#### Moje wnioski" in views["bob"]["content"] and "Do zatwierdzenia" not in views["bob"]["content"], views["bob"].get("app_view"))
    check("carol, a reviewer, also sees the queue waiting for her",
          "#### Moje wnioski" in views["carol"]["content"] and "#### Do zatwierdzenia" in views["carol"]["content"], views["carol"].get("app_view"))
    check("dave, without requests.read, is told which permission the view needs",
          "Not readable for you (needs `requests.read`)" in views["dave"]["content"] and views["dave"]["app_view"]["error"] == "forbidden",
          views["dave"].get("app_view"))

    section("Publishers compare releases, users do not")
    versions = (await mcp("alice", "ics_asset_versions", {"slug_or_id": REQ["asset_id"]}))["versions"]
    check("the register has a package version per release", len(versions) >= 2, len(versions))
    newest, before = versions[0]["version"], versions[1]["version"]
    diff = await mcp("alice", "ics_asset_diff", {"slug_or_id": REQ["asset_id"], "v1": before, "v2": newest})
    check("a publisher's comparison lists files and what changed in the app",
          isinstance(diff.get("files"), list) and isinstance(diff.get("app_changes"), list), sorted(diff))
    denied = await mcp("bob", "ics_asset_diff", {"slug_or_id": REQ["asset_id"], "v1": before, "v2": newest}, expect_error=True)
    check("bob, who only uses the app, cannot compare its sources", "files" not in denied, denied)

    section("Publication failures")
    before = await status("alice", probe_id)
    plan, op = await publish("alice", "probe", probe_id, fault="fail:verify")
    failed = await wait_op("alice", op["operation_id"])
    after = await status("alice", probe_id)
    check("an injected failure ends the operation as failed with its code", failed["status"] == "failed" and failed["error"]["code"] == "fault_injected", failed.get("error"))
    check("the previous release stays active", after["active_release"]["id"] == before["active_release"]["id"], (before["active_release"]["id"], after["active_release"]["id"]))
    check("the panel shows the newer package as not active", after["package_version"] > after["active_release"]["package_version"])
    plan, op = await publish("alice", "probe", probe_id, fault="crash_after:migrate")
    t0 = time.time()
    resumed = await wait_op("alice", op["operation_id"], seconds=200)
    check("a worker crash mid-publication is resumed by the sweeper, not duplicated",
          resumed["status"] == "succeeded" and resumed["attempts"] >= 2, (resumed["status"], resumed["attempts"], round(time.time() - t0)))

    section("Sources stay private")
    meta_slug = (await status("alice", REQ["asset_id"]))["slug"]
    pkg = await mcp("alice", "ics_asset_read", {"slug_or_id": meta_slug, "path": "handlers/approve.mjs"})
    check("the publisher reads a handler through the author route", "export default async function approve" in pkg.get("content", ""))
    denied = await mcp("bob", "ics_asset_read", {"slug_or_id": meta_slug, "path": "handlers/approve.mjs"}, expect_error=True)
    check("a user of the app cannot read its handler (publish_permission_required)", "publish_permission_required" in json.dumps(denied), denied)
    files = await mcp("bob", "ics_asset_list_files", {"slug_or_id": meta_slug}, expect_error=True)
    check("nor list its package files", "publish_permission_required" in json.dumps(files), files)
    found = await mcp("bob", "ics_assets_search", {"q": "approve"})
    check("search does not surface handler code", all("ctx.db" not in json.dumps(h) for h in found.get("items", found.get("hits", []))))
    return probe_url


async def lifecycle_scenarios() -> None:
    section("Suspend, restart, enable")
    st = await status("alice", REQ["asset_id"])
    op = await mcp("alice", "ics_microapp_control", {"asset_id": REQ["asset_id"], "action": "suspend", "expected_generation": st["generation"], "confirm": True})
    check("suspend finishes after a confirmed drain", op["status"] == "succeeded", op)

    def suspended_page() -> None:
        with sync_playwright() as p:
            br = B.launch(p)
            bob = B.login(br, "bob")
            page = bob.new_page()
            # Sign in to the app origin first (launch still works), then ask.
            page.goto(REQ["app_url"])
            api = page.goto(REQ["app_url"] + "api/v1/session")
            check("a suspended app answers 503 app_suspended", api.status == 503 and api.json()["code"] == "app_suspended", api.status)
            br.close()

    await asyncio.to_thread(suspended_page)
    compose("restart", "broker", "backend", "arq-worker")
    wait_ready()
    time.sleep(5)
    st = await status("alice", REQ["asset_id"])
    check("suspension survives a restart of broker, backend and worker", st["desired_state"] == "suspended", st["desired_state"])
    op = await mcp("alice", "ics_microapp_control", {"asset_id": REQ["asset_id"], "action": "enable", "expected_generation": st["generation"], "confirm": True})
    st = await status("alice", REQ["asset_id"])
    check("enable restores enabled + sleeping (nothing starts until a request)", st["desired_state"] == "enabled" and st["runtime"]["state"] in ("sleeping", "unknown"), st["runtime"])

    def persisted() -> None:
        with sync_playwright() as p:
            br = B.launch(p)
            bob = B.login(br, "bob")
            pb = B.open_app(bob, REQ["app_url"])
            r = coll(pb, "requests", "list", {"limit": 200})
            check("data persisted across the restarts", r["ok"] and any(i["title"] == "Monitor 27 cali" for i in r["data"]["items"]), r.get("status"))
            br.close()

    await asyncio.to_thread(persisted)
    time.sleep(12)
    st = await status("alice", REQ["asset_id"])
    check("after a real request the runtime reports the app as ready", st["runtime"]["state"] in ("ready", "running"), st["runtime"])
    op = await mcp("alice", "ics_microapp_control", {"asset_id": REQ["asset_id"], "action": "sleep", "expected_generation": st["generation"], "confirm": True})
    time.sleep(12)
    st = await status("alice", REQ["asset_id"])
    check("sleep releases the app's pools and runner leases", st["runtime"]["state"] == "sleeping" and st["runtime"]["open_connections"] == 0, st["runtime"])
    logs = await mcp("alice", "ics_microapp_logs", {"asset_id": REQ["asset_id"], "limit": 20})
    check("logs record control actions without secrets", any("requested" in x["message"] for x in logs["items"]) and "password" not in json.dumps(logs).lower())


def main() -> None:
    L.assert_local_target()
    started = time.time()
    try:
        probe_url = asyncio.run(mcp_scenarios())
        browser_scenarios(probe_url)
        asyncio.run(lifecycle_scenarios())
    except Exception as e:
        traceback.print_exc()
        check("acceptance run completed without an unexpected error", False, f"{type(e).__name__}: {e}")
    failed = [r for r in RESULTS if not r["ok"]]
    report = {"finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "seconds": round(time.time() - started),
              "passed": len(RESULTS) - len(failed), "failed": len(failed), "results": RESULTS}
    (L.STATE / "acceptance-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\nacceptance: {report['passed']} passed, {report['failed']} failed in {report['seconds']} s")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
