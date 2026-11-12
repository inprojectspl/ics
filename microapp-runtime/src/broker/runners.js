// Global pool of runner slots (two by default, independent of the number of
// assets). One request per slot, at most one slot per asset, a bounded queue
// with deadlines. A lease binds a slot to (asset, environment, release,
// policy generation); a different key recycles the child process.
import crypto from "node:crypto";
import net from "node:net";
import { attachNdjson } from "../shared/ndjson.js";
import { DataError } from "./data.js";

const RECONNECT_MS = 1000;

class Slot {
  constructor(id, socketPath, onEvent) {
    this.id = id;
    this.socketPath = socketPath;
    this.onEvent = onEvent;
    this.state = "failed"; // idle | leased | busy | recycling | failed
    this.key = null;
    this.childPid = null;
    this.lease = null;
    this.waiters = new Map(); // message type:leaseId/reqId -> resolver
    this.active = null; // { reqId, onRpc, onLog, resolve, reject }
    this.connect();
  }

  connect() {
    const socket = net.createConnection(this.socketPath);
    socket.on("connect", () => {
      this.send = attachNdjson(socket, (m) => this.onMessage(m), () => {});
      this.state = "idle";
      this.key = null;
      this.onEvent("slot_ready", this);
    });
    socket.on("error", () => {});
    socket.on("close", () => {
      const wasActive = this.active;
      this.state = "failed";
      this.send = null;
      this.key = null;
      this.lease = null;
      for (const w of this.waiters.values()) w.reject(new DataError(503, "runner_unavailable", "runner disconnected"));
      this.waiters.clear();
      if (wasActive) {
        this.active = null;
        wasActive.reject(new DataError(503, "runner_unavailable", "runner disconnected"));
      }
      setTimeout(() => this.connect(), RECONNECT_MS).unref();
    });
  }

  waitFor(type, id, ms) {
    return new Promise((resolve, reject) => {
      const key = `${type}:${id}`;
      const timer = setTimeout(() => {
        this.waiters.delete(key);
        reject(new DataError(503, "runner_unavailable", `runner did not answer ${type}`));
      }, ms);
      timer.unref();
      this.waiters.set(key, {
        resolve: (v) => {
          clearTimeout(timer);
          resolve(v);
        },
        reject: (e) => {
          clearTimeout(timer);
          reject(e);
        },
      });
    });
  }

  settle(type, id, value) {
    const w = this.waiters.get(`${type}:${id}`);
    if (w) {
      this.waiters.delete(`${type}:${id}`);
      w.resolve(value);
    }
  }

  onMessage(m) {
    // Everything is checked against this slot's own lease record; stale or
    // foreign lease ids, nonces and request ids are dropped.
    const leaseOk = this.lease && m.leaseId === this.lease.id && m.nonce === this.lease.nonce;
    switch (m.t) {
      case "leased":
      case "lease_failed":
        if (leaseOk) this.settle("lease", m.leaseId, m);
        return;
      case "recycled":
        this.settle("recycle", m.leaseId ?? "any", m);
        return;
      case "rpc":
        if (leaseOk && this.active && m.reqId === this.active.reqId && m.childPid === this.childPid) {
          this.active.onRpc(m.callId, m.method, m.args);
        }
        return;
      case "log":
        if (leaseOk && this.active && m.reqId === this.active.reqId) this.active.onLog?.(m.args);
        return;
      case "result":
      case "compiled":
        if (leaseOk && this.active && m.reqId === this.active.reqId) {
          const a = this.active;
          this.active = null;
          a.resolve(m);
        }
        return;
      default:
    }
  }

  async ensureLease(key) {
    if (this.lease && this.key === key) return;
    const leaseId = crypto.randomUUID();
    const nonce = crypto.randomBytes(16).toString("base64url");
    this.lease = { id: leaseId, nonce };
    this.send({ t: "lease", leaseId, nonce, key });
    const reply = await this.waitFor("lease", leaseId, 5000);
    if (reply.t !== "leased") throw new DataError(503, "runner_unavailable", "lease failed");
    if (this.key !== key && this.childPid === reply.childPid && this.childPid !== null) {
      // The supervisor must have forked a new process for a new key.
      throw new DataError(500, "runner_reuse_violation", "runner reused a process across keys");
    }
    this.key = key;
    this.childPid = reply.childPid;
    this.onEvent("leased", this);
  }

  run(type, payload, { onRpc, onLog }) {
    const reqId = crypto.randomUUID();
    return {
      reqId,
      promise: new Promise((resolve, reject) => {
        this.active = { reqId, onRpc, onLog, resolve, reject };
        this.send({ t: type, leaseId: this.lease.id, nonce: this.lease.nonce, reqId, ...payload });
      }),
    };
  }

  rpcResult(reqId, callId, result) {
    if (!this.active || this.active.reqId !== reqId || !this.send) return;
    this.send({ t: "rpc_result", leaseId: this.lease.id, nonce: this.lease.nonce, reqId, callId, ...result });
  }

  async recycle(reason) {
    if (!this.send) return;
    this.state = "recycling";
    const leaseId = this.lease?.id ?? "any";
    this.send({ t: "recycle", leaseId: this.lease?.id, reason });
    this.lease = null;
    this.key = null;
    this.childPid = null;
    if (this.active) {
      const a = this.active;
      this.active = null;
      a.reject(new DataError(504, "execution_deadline", "handler stopped"));
    }
    try {
      await this.waitFor("recycle", leaseId, 3000);
    } catch {
      // The socket close handler takes over if the supervisor is gone.
    }
    if (this.send) this.state = "idle";
  }
}

export class RunnerPool {
  constructor({ sockets, queueMax = 32, perAssetQueueMax = 4 }) {
    this.queue = [];
    this.queueMax = queueMax;
    this.perAssetQueueMax = perAssetQueueMax;
    this.events = [];
    this.slots = sockets.map((path, i) => new Slot(i + 1, path, (event, slot) => this.#onSlotEvent(event, slot)));
  }

  #onSlotEvent(event, slot) {
    if (event === "slot_ready") this.#dispatch();
  }

  snapshot() {
    return this.slots.map((s) => ({ id: s.id, state: s.state, key: s.key ? s.key.split("|")[0] : null, childPid: s.childPid }));
  }

  queuedFor(assetKey) {
    return this.queue.filter((q) => q.assetKey === assetKey).length;
  }

  busyFor(assetKey) {
    return this.slots.some((s) => (s.state === "busy" || s.state === "leased") && s.key?.startsWith(`${assetKey}|`));
  }

  /** Wait for a free slot for `assetKey`, honouring global and per-asset limits. */
  acquire(assetKey, leaseKey, deadline) {
    if (this.queue.length >= this.queueMax) {
      return Promise.reject(new DataError(503, "capacity_exhausted", "the execution queue is full", { retryAfter: 1 }));
    }
    if (this.queuedFor(assetKey) >= this.perAssetQueueMax) {
      return Promise.reject(new DataError(429, "rate_limited", "too many queued requests for this application", { retryAfter: 1 }));
    }
    return new Promise((resolve, reject) => {
      const item = { assetKey, leaseKey, resolve, reject, deadline };
      item.timer = setTimeout(() => {
        const i = this.queue.indexOf(item);
        if (i >= 0) this.queue.splice(i, 1);
        reject(new DataError(503, "capacity_exhausted", "no execution slot within the deadline", { retryAfter: 1 }));
      }, Math.max(0, deadline - Date.now()));
      item.timer.unref();
      this.queue.push(item);
      this.#dispatch();
    });
  }

  #dispatch() {
    for (let i = 0; i < this.queue.length; i += 1) {
      const item = this.queue[i];
      if (this.busyFor(item.assetKey)) continue; // at most one slot per asset
      const idle = this.slots.filter((s) => s.state === "idle");
      if (!idle.length) return;
      // Prefer a slot already leased to this key: no process restart needed.
      const slot = idle.find((s) => s.key === item.leaseKey) ?? idle.find((s) => !s.key) ?? idle[0];
      this.queue.splice(i, 1);
      i -= 1;
      clearTimeout(item.timer);
      slot.state = "busy";
      item.resolve(slot);
    }
  }

  release(slot, { recycle, reason } = {}) {
    const done = () => {
      if (slot.state === "busy") slot.state = "idle";
      this.#dispatch();
    };
    if (recycle) slot.recycle(reason).finally(done);
    else done();
  }

  /** Recycle every slot leased to an asset (restart, suspend, policy change). */
  async recycleAsset(assetKey, reason) {
    await Promise.all(this.slots.filter((s) => s.key?.startsWith(`${assetKey}|`) && s.state !== "busy").map((s) => s.recycle(reason)));
  }
}
