// Slot accounting of the broker runner pool against fake supervisors whose
// lease replies the test releases by hand: at most one slot per asset even
// while the lease of a cold slot is still unconfirmed.
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { after, before, test } from "node:test";
import assert from "node:assert/strict";
import { attachNdjson } from "../src/shared/ndjson.js";
import { RunnerPool } from "../src/broker/runners.js";

const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ics-runner-pool-"));
const supervisors = [];
let pool;
let nextPid = 1000;

function fakeSupervisor(socketPath) {
  const sup = { leases: [], sockets: new Set(), server: null };
  sup.server = net.createServer((socket) => {
    sup.sockets.add(socket);
    socket.on("close", () => sup.sockets.delete(socket));
    socket.on("error", () => {});
    const send = attachNdjson(socket, (m) => {
      if (m.t === "lease") sup.leases.push({ ...m, send });
      if (m.t === "recycle") send({ t: "recycled", leaseId: m.leaseId ?? "any" });
    }, () => {});
  });
  sup.listen = () => new Promise((resolve) => sup.server.listen(socketPath, resolve));
  // Answer the oldest pending lease request.
  sup.answer = (ok = true) => {
    const m = sup.leases.shift();
    m.send({ t: ok ? "leased" : "lease_failed", leaseId: m.leaseId, nonce: m.nonce, childPid: (nextPid += 1) });
  };
  sup.drop = () => {
    for (const s of sup.sockets) s.destroy();
  };
  return sup;
}

const tick = () => new Promise((r) => setImmediate(r));

async function until(cond, what) {
  for (let i = 0; i < 200; i += 1) {
    if (cond()) return;
    await new Promise((r) => setTimeout(r, 10));
  }
  throw new Error(`timed out waiting for ${what}`);
}

const leaseRequests = () => supervisors.reduce((n, s) => n + s.leases.length, 0);
const supervisorOf = (slot) => supervisors[slot.id - 1];

// Resolves to the slot, or "queued" if it has not been handed out yet.
async function settledOrQueued(promise) {
  await tick();
  return Promise.race([promise, Promise.resolve("queued")]);
}

before(async () => {
  for (const name of ["1.sock", "2.sock"]) {
    const sup = fakeSupervisor(path.join(dir, name));
    await sup.listen();
    supervisors.push(sup);
  }
  pool = new RunnerPool({ sockets: supervisors.map((s) => s.server.address()) });
  await until(() => pool.slots.every((s) => s.state === "idle"), "slots to connect");
});

after(() => {
  for (const s of supervisors) {
    s.drop();
    s.server.close();
  }
  fs.rmSync(dir, { recursive: true, force: true });
});

test("a second request of a cold app waits while its lease is unconfirmed", async () => {
  const deadline = Date.now() + 3000;
  const slotA = await pool.acquire("app-a", "app-a|rel1|1", deadline);
  const leasing = slotA.ensureLease("app-a|rel1|1");
  assert.equal(slotA.key, null);

  const secondA = pool.acquire("app-a", "app-a|rel1|1", deadline);
  const slotB = await pool.acquire("app-b", "app-b|rel1|1", deadline);
  assert.notEqual(slotB, slotA);
  assert.equal(await settledOrQueued(secondA), "queued");
  assert.equal(pool.queuedFor("app-a"), 1);

  await until(() => leaseRequests() === 1, "lease request");
  supervisorOf(slotA).answer();
  await leasing;
  assert.equal(slotA.key, "app-a|rel1|1");
  assert.equal(await settledOrQueued(secondA), "queued");

  pool.release(slotB);
  pool.release(slotA);
  // The warm slot of app-a is preferred over the one app-b just gave back.
  assert.equal(await secondA, slotA);
  await slotA.ensureLease("app-a|rel1|1");
  assert.equal(leaseRequests(), 0);
  pool.release(slotA);
});

test("a failed lease does not leave the asset reserved", async () => {
  const deadline = Date.now() + 3000;
  const slot = await pool.acquire("app-c", "app-c|rel1|1", deadline);
  const leasing = slot.ensureLease("app-c|rel1|1");
  const second = pool.acquire("app-c", "app-c|rel1|1", deadline);
  await until(() => leaseRequests() === 1, "lease request");
  supervisorOf(slot).answer(false);
  await assert.rejects(leasing, { code: "runner_unavailable" });
  assert.equal(await settledOrQueued(second), "queued");

  pool.release(slot, { recycle: true, reason: "lease failed" });
  const next = await second;
  assert.equal(pool.busyFor("app-c"), true);
  pool.release(next);
  assert.equal(pool.busyFor("app-c"), false);
});

test("a lost runner connection does not leave a stuck reservation", async () => {
  const deadline = Date.now() + 5000;
  const slot = await pool.acquire("app-d", "app-d|rel1|1", deadline);
  const leasing = slot.ensureLease("app-d|rel1|1");
  await until(() => leaseRequests() === 1, "lease request");
  supervisorOf(slot).leases.length = 0;
  supervisorOf(slot).drop();
  await assert.rejects(leasing, { code: "runner_unavailable" });
  assert.equal(pool.busyFor("app-d"), true);

  // Reconnecting does not hand the slot out while its holder keeps it.
  await until(() => slot.send, "reconnect");
  assert.equal(slot.state, "busy");

  pool.release(slot);
  assert.equal(pool.busyFor("app-d"), false);
  assert.equal(slot.state, "idle");
  const again = await pool.acquire("app-d", "app-d|rel1|1", deadline);
  pool.release(again);
});
