// The per-app circuit breaker: what counts as a failure, that one failed
// request counts once, and that a restart from ICS clears it.
import { test } from "node:test";
import assert from "node:assert/strict";
import { adminHandler } from "../src/broker/admin.js";
import { AppRegistry } from "../src/broker/apps.js";
import { invokeHandler } from "../src/broker/custom.js";

const RELEASE = "rel-1";

function registry() {
  const r = new AppRegistry({ ics: null, pools: { closeApp() {} }, runners: { async recycleAsset() {} }, idleSeconds: 600 });
  const app = r.get("a".repeat(32), "prod");
  return { r, app };
}

function handlerCall(slotResult) {
  const { r, app } = registry();
  const released = [];
  const slot = {
    async ensureLease() {},
    run: () => ({ reqId: "q1", promise: slotResult }),
  };
  const gw = { apps: r, runners: { acquire: async () => slot, release: (s, opts) => released.push(opts) } };
  const rc = {
    app,
    bundle: { handlers: { "finish.js": "export default async () => ({ status: 200 })" } },
    model: {},
    auth: { release: { id: RELEASE }, user: { id: "u1" }, roles: [], asset_id: "x", data_generation: 1, policy_generation: 1 },
    permissions: new Set(),
    target: { environment: "prod" },
    requestId: "r1",
  };
  const endpoint = { handler: "finish.js#default", capabilities: [], transaction: "required" };
  const limits = { wallMs: 50, queueMs: 50, cpuMs: 1000, memoryBytes: 1, stackBytes: 1, maxDbCalls: 1, maxResponseBytes: 1 };
  return { r, app, released, run: () => invokeHandler(gw, rc, endpoint, {}, undefined, {}, {}, limits) };
}

test("a spent CPU budget answers with its own code and counts once", async () => {
  const { r, app, released, run } = handlerCall(Promise.resolve({ ok: false, error: { code: "cpu_budget" } }));
  await assert.rejects(run(), (e) => e.status === 504 && e.code === "cpu_budget");
  assert.equal(app.failures.length, 1);
  assert.equal(app.lastErrorCode, "cpu_budget");
  assert.deepEqual(released, [{ recycle: true, reason: "cpu_budget" }]);
  // The transaction around the handler reports the same request again.
  r.recordFailure(app, RELEASE, "execution_deadline", "r1");
  assert.equal(app.failures.length, 1);
});

test("a stalled handler recycles its runner without counting towards the breaker", async () => {
  const { app, released, run } = handlerCall(Promise.resolve({ ok: false, error: { code: "handler_stalled" } }));
  await assert.rejects(run(), (e) => e.status === 504 && e.code === "handler_stalled");
  assert.equal(app.failures.length, 0);
  assert.deepEqual(released, [{ recycle: true, reason: "handler_stalled" }]);
});

test("a restart from the panel closes the breaker at once", async () => {
  const { r, app } = registry();
  for (let i = 0; i < 3; i++) r.recordFailure(app, RELEASE, "execution_deadline", `q${i}`);
  assert.equal(r.breakerOpen(app), true);
  const handler = adminHandler({ config: { serviceToken: "s" }, apps: r, runners: null, gateway: null, incarnation: "i" });
  const res = { writeHead(s) { this.status = s; }, end() {} };
  await handler({ method: "POST", url: `/admin/apps/${"a".repeat(32)}/prod/restart`, headers: { "x-ics-service-token": "s" } }, res);
  assert.equal(res.status, 200);
  assert.equal(r.breakerOpen(app), false);
});

test("three failures of one release open the breaker", () => {
  const { r, app } = registry();
  r.recordFailure(app, RELEASE, "cpu_budget");
  r.recordFailure(app, RELEASE, "handler_failed");
  r.recordFailure(app, RELEASE, "execution_deadline");
  assert.equal(r.breakerOpen(app), false);
  r.recordFailure(app, RELEASE, "memory_limit");
  assert.equal(r.breakerOpen(app), true);
});

test("a restart from ICS closes the breaker", async () => {
  const { r, app } = registry();
  await r.sync(app, { asset_id: "x", control_generation: 1, desired_state: "enabled" });
  for (let i = 0; i < 3; i++) r.recordFailure(app, RELEASE, "execution_deadline");
  assert.equal(r.breakerOpen(app), true);
  await r.sync(app, { asset_id: "x", control_generation: 1, desired_state: "enabled" });
  assert.equal(r.breakerOpen(app), true);
  await r.sync(app, { asset_id: "x", control_generation: 2, desired_state: "enabled" });
  assert.equal(r.breakerOpen(app), false);
  r.recordFailure(app, RELEASE, "execution_deadline");
  assert.equal(r.breakerOpen(app), false);
});
