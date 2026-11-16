"""Create the two pilot micro-applications through the local ICS-MCP server
(plan -> apply -> status), then give people access with
`ics_microapp_access_set` with the apps' roles, the way an agent does it.

Idempotent: an app that already exists (same title, owned by alice) gets a
new plan only when its package changed; access is set to the same target
state on every run.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any


sys.path.insert(0, str(Path(__file__).parent))
import localenv as L  # noqa: E402

APPS = {
    "requests": {
        "title": "Request register",
        "share": ["bob", "carol", "dave"],
        # Roles from the manifest; single permissions beside them where a
        # person needs a mix no role gives (carol files requests and reviews).
        "grants": {
            "bob": {"roles": ["employee"]},
            "carol": {"roles": ["reviewer"], "permissions": ["requests.create", "requests.read"]},
        },
    },
    "equipment": {
        "title": "Equipment booking",
        "share": ["bob", "carol", "dave"],
        "grants": {
            "alice": {"roles": ["keeper"]},
            "bob": {"roles": ["borrower"]},
            "carol": {"roles": ["borrower"]},
        },
    },
}
STATE_FILE = L.STATE / "apps.json"


async def wait_operation(client: Any, op_id: str, timeout_s: float = 240) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        op = await L.call(client, "ics_microapp_status", {"operation_id": op_id})
        if op["terminal"]:
            return op
        await asyncio.sleep(2)
    raise TimeoutError(op_id)


async def publish(client: Any, name: str, asset_id: str | None) -> dict[str, Any]:
    args: dict[str, Any] = {"files": L.package_files(name)}
    if asset_id:
        args["asset_id"] = asset_id
    plan = await L.call(client, "ics_microapp_plan", args)
    print(f"  plan {plan['plan_id']} {plan['action']} digest={plan['release_digest'][:19]} "
          f"schema {plan['database']['schema_version_from']}->{plan['database']['schema_version_to']}")
    op = await L.call(client, "ics_microapp_apply", {
        "plan_id": plan["plan_id"], "digest": plan["release_digest"],
        "expected_generation": plan["expected_generation"], "confirm": True,
    })
    print(f"  apply -> {op['operation_id']} ({op['status']})")
    done = await wait_operation(client, op["operation_id"])
    if done["status"] != "succeeded":
        raise RuntimeError(f"publication failed: {json.dumps(done)[:800]}")
    print(f"  {done['status']}: release {done['release_id']} steps={[s['step'] for s in done['steps']]}")
    return {"asset_id": done["asset_id"], "app_url": done["app_url"], "operation_id": done["operation_id"],
            "plan": plan}


async def outdated(client: Any, name: str, asset_id: str) -> bool:
    """The active release's manifest differs from the local example."""
    local = json.loads((L.EXAMPLES / name / "microapp.json").read_text())
    active = await L.call(client, "ics_asset_read", {"slug_or_id": asset_id, "path": "microapp.json"})
    return json.loads(active["content"]) != local


async def main() -> None:
    L.assert_local_target()
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    async with L.mcp_client("alice") as client:
        who = await L.call(client, "ics_whoami")
        if who["email"] != "alice@example.com":
            sys.exit(f"MCP session belongs to {who['email']}, expected alice")
        print(f"local MCP session: {who['email']} at {L.BASE_URL}")
        listing = await L.call(client, "ics_microapp_status", {"limit": 50})
        by_title = {i["title"]: i for i in listing["items"]}
        for name, spec in APPS.items():
            print(f"{name}:")
            existing = by_title.get(spec["title"])
            if existing and existing["release"] is None:
                print(f"  {existing['asset_id']} has no active release: publishing again")
                state[name] = await publish(client, name, existing["asset_id"])
            elif existing and await outdated(client, name, existing["asset_id"]):
                print(f"  {existing['asset_id']} runs an older package: publishing the local one")
                state[name] = await publish(client, name, existing["asset_id"])
            elif existing:
                state[name] = {**state.get(name, {}), "asset_id": existing["asset_id"], "app_url": existing["app_url"]}
                print(f"  exists: {existing['asset_id']} ({existing['desired_state']}, release {existing['release']})")
            else:
                state[name] = await publish(client, name, None)
        STATE_FILE.write_text(json.dumps(state, indent=2))

        for name, spec in APPS.items():
            asset_id = state[name]["asset_id"]
            for who in sorted(set(spec["share"]) | set(spec["grants"])):
                await L.call(client, "ics_microapp_access_set", {
                    "asset_id": asset_id, "user_email": L.email(who),
                    **spec["grants"].get(who, {}), "can_open": True, "confirm": True,
                })
            print(f"{name}: open for {spec['share']}, roles for {sorted(spec['grants'])}; {state[name]['app_url']}")


if __name__ == "__main__":
    asyncio.run(main())
