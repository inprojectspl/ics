// Runner supervisor + child + broker slot pool, end to end over a real Unix
// socket: async RPC bridge, CPU and memory limits, process recycling between
// keys and refusal of stale or foreign messages.
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { after, before, test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { RunnerPool } from "../src/broker/runners.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ics-runner-"));
const sockets = [path.join(dir, "1.sock"), path.join(dir, "2.sock")];
const procs = [];
let pool;

const LIMITS = { memoryBytes: 32 << 20, cpuMs: 250, wallMs: 3000, stackBytes: 512 * 1024 };

async function waitFor(file) {
  for (let i = 0; i < 100; i += 1) {
    if (fs.existsSync(file)) return;
    await new Promise((r) => setTimeout(r, 50));
  }
  throw new Error(`socket ${file} not created`);
}

before(async () => {
  for (const [i, socket] of sockets.entries()) {
    const p = spawn(process.execPath, [path.join(here, "../src/runner/supervisor.js")], {
      env: { ...process.env, ICS_RUNNER_SOCKET: socket, ICS_RUNNER_ID: String(i + 1) },
      stdio: ["ignore", "ignore", "ignore"],
    });
    procs.push(p);
    await waitFor(socket);
  }
  pool = new RunnerPool({ sockets });
  for (let i = 0; i < 50 && pool.slots.some((s) => s.state !== "idle"); i += 1) await new Promise((r) => setTimeout(r, 50));
});

after(() => {
  for (const p of procs) p.kill("SIGKILL");
  fs.rmSync(dir, { recursive: true, force: true });
});

async function invoke(assetKey, code, { input = { params: {} }, rpc = async () => null, limits = LIMITS } = {}) {
  const leaseKey = `${assetKey}|rel1|1`;
  const slot = await pool.acquire(assetKey, leaseKey, Date.now() + 2000);
  let recycle = false;
  try {
    await slot.ensureLease(leaseKey);
    const pid = slot.childPid;
    const job = slot.run(
      "invoke",
      { code, filename: "handlers/t.mjs", input, context: { actor: { id: "u1" }, app: { id: assetKey }, request: { id: "r1", preconditions: { revision: 3 } } }, limits },
      {
        onRpc: async (callId, method, args) => {
          try {
            slot.rpcResult(job.reqId, callId, { ok: true, value: await rpc(method, args) });
          } catch (err) {
            slot.rpcResult(job.reqId, callId, { ok: false, error: { code: err.code, message: err.message, status: err.status } });
          }
        },
      },
    );
    const result = await job.promise;
    if (!result.ok) recycle = true;
    return { result, pid, slot };
  } finally {
    pool.release(slot, { recycle });
  }
}

test("handler awaits several broker RPCs and returns JSON", async () => {
  const calls = [];
  const { result } = await invoke(
    "app-a",
    `export default async function (input, ctx) {
      const a = await ctx.db.get("requests", "id-1", { capability: "x" });
      const [b, c] = await Promise.all([ctx.db.count("requests", [], { capability: "y" }), ctx.db.count("requests", [], { capability: "y" })]);
      return { status: 200, body: { a, b, c, rev: ctx.request.preconditions.revision } };
    }`,
    { rpc: async (method, args) => (calls.push(method), method === "db.get" ? { id: args[1] } : 2) },
  );
  assert.equal(result.ok, true);
  assert.deepEqual(result.value, { status: 200, body: { a: { id: "id-1" }, b: 2, c: 2, rev: 3 } });
  assert.deepEqual(calls, ["db.get", "db.count", "db.count"]);
});

test("a rejected RPC surfaces as a catchable guest error with its status", async () => {
  const { result } = await invoke(
    "app-a",
    `export default async function (input, ctx) {
      try { await ctx.db.update("requests", "x", {}, { capability: "c", ifRevision: 1 }); }
      catch (e) { return { status: 200, body: { code: e.code, status: e.status } }; }
    }`,
    { rpc: async () => Promise.reject(Object.assign(new Error("changed"), { code: "revision_mismatch", status: 412 })) },
  );
  assert.deepEqual(result.value.body, { code: "revision_mismatch", status: 412 });
});

test("an endless loop is interrupted by the CPU budget", async () => {
  const started = Date.now();
  const { result } = await invoke("app-a", "export default async function () { for (;;) {} }");
  assert.equal(result.ok, false);
  assert.equal(result.error.code, "cpu_budget");
  assert.ok(Date.now() - started < 2000);
});

test("a large allocation is stopped inside the runner, never in the supervisor", async () => {
  const { result } = await invoke("app-a", "export default async function () { const a = []; for (;;) a.push(new Array(1e6).fill(1)); }", { limits: { ...LIMITS, cpuMs: 5000 } });
  assert.equal(result.ok, false);
  // The guest heap limit normally answers first; under a tight OS memory
  // limit (a small container) the child is killed instead. Either way only
  // the child dies and the same slot serves the next call.
  assert.ok(["memory_limit", "runner_killed", "runner_crashed"].includes(result.error.code), result.error.code);
  const { result: next } = await invoke("app-a", "export default async function () { return { status: 200, body: 1 }; }");
  assert.equal(next.ok, true);
});

test("no Node or network API is reachable from guest code", async () => {
  const { result } = await invoke("app-a", "export default async function () { return { status: 200, body: [typeof process, typeof require, typeof fetch, typeof globalThis.__ics_call, typeof XMLHttpRequest] }; }");
  assert.deepEqual(result.value.body, ["undefined", "undefined", "undefined", "undefined", "undefined"]);
});

test("guest state does not survive between calls of the same key", async () => {
  await invoke("app-b", "export default async function () { globalThis.leak = 'secret'; return { status: 200, body: null }; }");
  const { result } = await invoke("app-b", "export default async function () { return { status: 200, body: typeof globalThis.leak }; }");
  assert.equal(result.value.body, "undefined");
});

test("a different asset key gets a new child process (new PID)", async () => {
  const first = await invoke("app-c", "export default async function () { return { status: 200, body: 1 }; }");
  // Force both calls onto the same slot by occupying nothing else: compare
  // every slot's current child against the PID used for app-c.
  const second = await invoke("app-d", "export default async function () { return { status: 200, body: 2 }; }");
  if (second.slot === first.slot) assert.notEqual(second.pid, first.pid);
  for (const s of pool.slots) if (s.key?.startsWith("app-d|")) assert.notEqual(s.childPid, first.pid);
});

test("messages with a stale lease nonce are ignored", async () => {
  const leaseKey = "app-e|rel1|1";
  const slot = await pool.acquire("app-e", leaseKey, Date.now() + 2000);
  try {
    await slot.ensureLease(leaseKey);
    let spoofed = false;
    slot.active = { reqId: "r-x", onRpc: () => (spoofed = true), resolve: () => {}, reject: () => {} };
    slot.onMessage({ t: "rpc", leaseId: slot.lease.id, nonce: "forged", reqId: "r-x", callId: 1, method: "db.get", args: [], childPid: slot.childPid });
    assert.equal(spoofed, false);
    slot.active = null;
  } finally {
    pool.release(slot);
  }
});
