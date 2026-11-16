// Runner supervisor: one per runner slot (container / systemd unit).
//
// Listens on a Unix socket only the broker can reach and owns at most one
// child process. The child is bound to a lease key; a different key, a
// timeout, a crash or a protocol error means: kill the child, fork a new one.
// The supervisor stamps every relayed message with its own lease record, so a
// child cannot speak for another request or lease.
import { fork } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { attachNdjson } from "../shared/ndjson.js";

const SOCKET = process.env.ICS_RUNNER_SOCKET ?? "/run/ics-runner/runner.sock";
const RUNNER_ID = process.env.ICS_RUNNER_ID ?? "1";
const CHILD = path.join(path.dirname(fileURLToPath(import.meta.url)), "child.js");
const CHILD_HEAP_MB = Number(process.env.ICS_RUNNER_CHILD_HEAP_MB ?? 160);

let child = null; // { proc, key, pid, ready: Promise }
let lease = null; // { id, nonce, key, reqId }
let sendToBroker = null;
let generation = 0;

function log(event, fields = {}) {
  process.stderr.write(`${JSON.stringify({ ts: new Date().toISOString(), runner: RUNNER_ID, event, ...fields })}\n`);
}

function killChild(reason) {
  if (!child) return;
  const { proc, pid } = child;
  child = null;
  log("child_killed", { pid, reason });
  try {
    proc.kill("SIGKILL");
  } catch {
    // already gone
  }
}

function spawnChild(key) {
  generation += 1;
  const proc = fork(CHILD, [], {
    execArgv: [`--max-old-space-size=${CHILD_HEAP_MB}`, "--disallow-code-generation-from-strings"],
    serialization: "json",
    stdio: ["ignore", "inherit", "inherit", "ipc"],
    env: { NODE_ENV: "production" },
  });
  const record = { proc, key, pid: proc.pid, generation };
  record.ready = new Promise((resolve, reject) => {
    const onMessage = (m) => {
      if (m?.t === "ready") {
        proc.off("message", onMessage);
        resolve();
      }
    };
    proc.on("message", onMessage);
    proc.once("exit", () => reject(new Error("child exited before ready")));
  });
  proc.on("message", (m) => onChildMessage(record, m));
  proc.on("exit", (code, signal) => {
    if (child === record) child = null;
    if (lease && lease.childPid === record.pid && lease.reqId) {
      const reqId = lease.reqId;
      lease.reqId = null;
      sendToBroker?.({
        t: "result",
        leaseId: lease.id,
        nonce: lease.nonce,
        reqId,
        ok: false,
        error: { code: signal === "SIGKILL" ? "runner_killed" : "runner_crashed", message: `child exited (${signal ?? code})` },
        childPid: record.pid,
      });
    }
    log("child_exit", { pid: record.pid, code, signal });
  });
  child = record;
  log("child_spawned", { pid: proc.pid, generation });
  return record;
}

function onChildMessage(record, m) {
  if (!lease || lease.childPid !== record.pid) return;
  const stamp = { leaseId: lease.id, nonce: lease.nonce, childPid: record.pid };
  if (m.t === "rpc" || m.t === "log") {
    if (m.reqId !== lease.reqId) return;
    if (m.t === "rpc") {
      sendToBroker?.({ t: "rpc", ...stamp, reqId: m.reqId, callId: m.callId, method: m.method, args: m.args });
    } else {
      sendToBroker?.({ t: "log", ...stamp, reqId: m.reqId, args: m.args });
    }
    return;
  }
  if (m.t === "result" || m.t === "compiled") {
    if (m.reqId !== lease.reqId) return;
    lease.reqId = null;
    sendToBroker?.({ ...m, ...stamp });
    return;
  }
  // Anything else from a child is a protocol violation.
  killChild("child_protocol_violation");
}

async function ensureChild(key) {
  if (child && child.key === key) return child;
  killChild(child ? "lease_key_changed" : "fresh");
  const record = spawnChild(key);
  await record.ready;
  return record;
}

async function onBrokerMessage(m) {
  switch (m.t) {
    case "hello":
      sendToBroker({ t: "hello", runner: RUNNER_ID, pid: process.pid, childPid: child?.pid ?? null });
      return;
    case "lease": {
      // A new lease always starts from a known child state for its key.
      lease = { id: m.leaseId, nonce: m.nonce, key: m.key, reqId: null, childPid: null };
      try {
        const record = await ensureChild(m.key);
        lease.childPid = record.pid;
        sendToBroker({ t: "leased", leaseId: m.leaseId, nonce: m.nonce, childPid: record.pid });
      } catch (err) {
        sendToBroker({ t: "lease_failed", leaseId: m.leaseId, nonce: m.nonce, error: String(err.message) });
      }
      return;
    }
    case "invoke":
    case "compile": {
      if (!lease || m.leaseId !== lease.id || m.nonce !== lease.nonce || !child || child.pid !== lease.childPid) {
        sendToBroker({ t: "result", leaseId: m.leaseId, nonce: m.nonce, reqId: m.reqId, ok: false, error: { code: "stale_lease" } });
        return;
      }
      if (lease.reqId) {
        sendToBroker({ t: "result", leaseId: m.leaseId, nonce: m.nonce, reqId: m.reqId, ok: false, error: { code: "runner_busy" } });
        return;
      }
      lease.reqId = m.reqId;
      const { t, leaseId, nonce, ...rest } = m;
      child.proc.send({ t, ...rest });
      return;
    }
    case "rpc_result":
      if (!lease || m.leaseId !== lease.id || m.nonce !== lease.nonce || m.reqId !== lease.reqId || !child) return;
      child.proc.send({ t: "rpc_result", reqId: m.reqId, callId: m.callId, ok: m.ok, value: m.value, error: m.error });
      return;
    case "recycle":
      killChild(m.reason ?? "recycle");
      if (lease && (!m.leaseId || m.leaseId === lease.id)) lease = null;
      sendToBroker({ t: "recycled", leaseId: m.leaseId ?? null });
      return;
    case "release":
      if (lease && m.leaseId === lease.id) lease = null;
      return;
    default:
      log("unknown_broker_message", { type: m.t });
  }
}

function start() {
  try {
    fs.unlinkSync(SOCKET);
  } catch {
    // no stale socket
  }
  const server = net.createServer((socket) => {
    if (sendToBroker) {
      // One broker connection at a time; a reconnect replaces the old one.
      log("broker_reconnected");
    }
    killChild("broker_connection");
    lease = null;
    sendToBroker = attachNdjson(
      socket,
      (m) => {
        onBrokerMessage(m).catch((err) => log("broker_message_failed", { error: String(err.message) }));
      },
      (err) => log("broker_protocol_error", { error: err.message }),
    );
    socket.on("close", () => {
      killChild("broker_disconnected");
      lease = null;
      sendToBroker = null;
    });
  });
  server.listen(SOCKET, () => {
    fs.chmodSync(SOCKET, 0o660);
    log("listening", { socket: SOCKET, pid: process.pid });
  });
  for (const signal of ["SIGTERM", "SIGINT"]) {
    process.on(signal, () => {
      killChild("shutdown");
      server.close(() => process.exit(0));
      setTimeout(() => process.exit(0), 2000).unref();
    });
  }
}

start();
