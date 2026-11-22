// Global connection budget of the pool registry. The real pg-pool runs over a
// fake client whose handshakes the test completes by hand, so concurrent cold
// apps can be held mid-handshake deterministically.
import { EventEmitter } from "node:events";
import { beforeEach, test } from "node:test";
import assert from "node:assert/strict";
import pg from "pg";
import { PoolRegistry } from "../src/broker/db.js";

let handshakes = [];

class FakeClient extends EventEmitter {
  constructor() {
    super();
    this._queryable = true;
    this._ending = false;
  }

  connect(cb) {
    handshakes.push({ ok: () => cb(), fail: (err) => cb(err) });
  }

  isConnected() {
    return true;
  }

  end(cb) {
    this._ending = true;
    setImmediate(() => {
      this.emit("end");
      cb?.();
    });
  }

  ref() {}
  unref() {}
}

const RealPool = pg.Pool;
pg.Pool = class extends RealPool {
  constructor(options) {
    super({ ...options, Client: FakeClient });
  }
};

const binding = (app) => ({ asset_id: app, environment: "live", user: `rt_${app}`, credential_generation: 1, schema: app });
const tick = () => new Promise((r) => setImmediate(r));

beforeEach(() => {
  handshakes = [];
});

test("concurrent cold apps cannot overshoot the budget while handshaking", async () => {
  const reg = new PoolRegistry({ maxConnections: 2 });
  const a = reg.connect("a", binding("a"));
  const b = reg.connect("b", binding("b"));
  await assert.rejects(reg.connect("c", binding("c")), { status: 503, code: "capacity_exhausted" });
  assert.equal(handshakes.length, 2);
  assert.equal(reg.used, 2);

  for (const h of handshakes) h.ok();
  const clients = await Promise.all([a, b]);
  assert.equal(reg.used, 2);
  for (const c of clients) c.release();
});

test("a failed handshake frees exactly one place in the budget", async () => {
  const reg = new PoolRegistry({ maxConnections: 2 });
  const a = reg.connect("a", binding("a"));
  const b = reg.connect("b", binding("b"));
  handshakes[0].fail(new Error("connection refused"));
  await assert.rejects(a, { code: "database_unavailable" });
  assert.equal(reg.used, 1);

  const c = reg.connect("c", binding("c"));
  await assert.rejects(reg.connect("d", binding("d")), { code: "capacity_exhausted" });
  handshakes[1].ok();
  handshakes[2].ok();
  const clients = await Promise.all([b, c]);
  assert.equal(reg.used, 2);
  for (const cl of clients) cl.release();
});

test("idle clients still count against the budget", async () => {
  const reg = new PoolRegistry({ maxConnections: 2 });
  const first = reg.connect("a", binding("a"));
  const second = reg.connect("a", binding("a"));
  for (const h of handshakes) h.ok();
  const [busy, idle] = await Promise.all([first, second]);
  idle.release();
  await tick();
  assert.equal(reg.pools.get(reg.key(binding("a"))).pool.idleCount, 1);
  assert.equal(reg.used, 2);

  // app a still has a busy client, so its pool is not reclaimed.
  await assert.rejects(reg.connect("b", binding("b")), { code: "capacity_exhausted" });
  // The idle client is reused without a new reservation.
  const again = await reg.connect("a", binding("a"));
  assert.equal(again, idle);
  assert.equal(reg.used, 2);
  busy.release();
  again.release();
});
