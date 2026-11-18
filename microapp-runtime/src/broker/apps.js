// Per-application runtime state inside the broker. Nothing here is a source
// of authorization: desired state, release and permissions come from ICS on
// every request. This is cache, counters and the drain barrier.
import { Model } from "./model.js";

const BREAKER_WINDOW_MS = 60_000;
const BREAKER_THRESHOLD = 3;
const BREAKER_OPEN_MS = 30_000;
const BUNDLE_CACHE = 32;
const COUNTED_REQUESTS = 64;
// Failures that say the handler itself cannot finish; other errors only
// update the last error shown in the panel.
export const BREAKER_CODES = new Set(["execution_deadline", "cpu_budget", "memory_limit", "runner_crashed", "runner_killed"]);

export class AppRegistry {
  constructor({ ics, pools, runners, idleSeconds }) {
    this.ics = ics;
    this.pools = pools;
    this.runners = runners;
    this.idleSeconds = idleSeconds;
    this.apps = new Map();
    this.bundles = new Map(); // releaseId -> Promise<{bundle, model}>
    this.logs = [];
  }

  key(assetHex, environment) {
    return `${assetHex}:${environment}`;
  }

  get(assetHex, environment) {
    const key = this.key(assetHex, environment);
    let app = this.apps.get(key);
    if (!app) {
      app = {
        key,
        assetHex,
        environment,
        assetId: null,
        state: "sleeping",
        inflight: 0,
        lastUsed: null,
        controlGeneration: null,
        binding: null,
        blocked: false,
        failures: [],
        countedRequests: [],
        breakerOpenUntil: 0,
        lastErrorCode: null,
        lastErrorAt: null,
        releaseId: null,
      };
      this.apps.set(key, app);
    }
    return app;
  }

  /** Align the cached context with the authorization answer. */
  async sync(app, auth) {
    app.assetId = auth.asset_id;
    if (app.controlGeneration !== null && app.controlGeneration !== auth.control_generation) {
      // restart / enable / policy change from ICS: start from a clean context,
      // including the breaker, so a restart lets the app run again at once
      this.resetBreaker(app);
      await this.sleep(app, "control_generation_changed");
    }
    app.controlGeneration = auth.control_generation;
    if (auth.desired_state === "enabled") app.blocked = false;
  }

  async model(releaseId) {
    let entry = this.bundles.get(releaseId);
    if (!entry) {
      entry = this.ics.bundle(releaseId).then((bundle) => ({ bundle, model: new Model(bundle.manifest, bundle.schema) }));
      entry.catch(() => this.bundles.delete(releaseId));
      this.bundles.set(releaseId, entry);
      while (this.bundles.size > BUNDLE_CACHE) this.bundles.delete(this.bundles.keys().next().value);
    }
    return entry;
  }

  async binding(app, credentialGeneration) {
    if (!app.binding || app.binding.credential_generation !== credentialGeneration) {
      app.binding = await this.ics.binding(app.assetId, app.environment);
    }
    return app.binding;
  }

  begin(app) {
    app.inflight += 1;
    app.state = "running";
    app.lastUsed = Date.now();
  }

  end(app) {
    app.inflight -= 1;
    app.lastUsed = Date.now();
    if (app.inflight === 0 && app.state === "running") app.state = "ready";
    if (app.inflight === 0 && app.drainWaiters) {
      for (const w of app.drainWaiters) w();
      app.drainWaiters = null;
    }
  }

  /** `requestId` makes a request count once, however many layers report it. */
  recordFailure(app, releaseId, code, requestId) {
    const now = Date.now();
    app.lastErrorCode = code;
    app.lastErrorAt = new Date(now).toISOString();
    if (!BREAKER_CODES.has(code)) return;
    if (requestId) {
      if (app.countedRequests.includes(requestId)) return;
      app.countedRequests.push(requestId);
      if (app.countedRequests.length > COUNTED_REQUESTS) app.countedRequests.shift();
    }
    app.failures = app.failures.filter((f) => now - f.at < BREAKER_WINDOW_MS && f.release === releaseId);
    app.failures.push({ at: now, release: releaseId });
    if (app.failures.length >= BREAKER_THRESHOLD) {
      app.breakerOpenUntil = now + BREAKER_OPEN_MS;
      app.failures = [];
      this.log(app, "error", "runtime", null, releaseId, "circuit breaker opened after repeated failures", { code });
    }
  }

  resetBreaker(app) {
    app.failures = [];
    app.breakerOpenUntil = 0;
  }

  breakerOpen(app) {
    return app.breakerOpenUntil > Date.now();
  }

  log(app, level, source, requestId, releaseId, message, fields = {}) {
    this.logs.push({ asset_id: app.assetId, environment: app.environment, level, source, request_id: requestId, release_id: releaseId, message, fields, ts: new Date().toISOString() });
    if (this.logs.length > 500) this.logs.splice(0, this.logs.length - 500);
  }

  async waitIdle(app, ms) {
    if (app.inflight === 0) return true;
    return new Promise((resolve) => {
      const timer = setTimeout(() => resolve(false), ms);
      timer.unref();
      (app.drainWaiters ??= []).push(() => {
        clearTimeout(timer);
        resolve(true);
      });
    });
  }

  /** Release every resource of the app; the next valid request wakes it up. */
  async sleep(app, reason) {
    this.pools.closeApp(app.key);
    await this.runners.recycleAsset(app.key, reason);
    app.binding = null;
    if (app.inflight === 0) app.state = "sleeping";
  }

  /** Suspend barrier: refuse new work, wait for in-flight work, then sleep. */
  async drain(app, ms = 8000) {
    app.blocked = true;
    app.state = "draining";
    const idle = await this.waitIdle(app, ms);
    await this.sleep(app, "suspend");
    app.state = idle ? "sleeping" : "draining";
    return { drained: idle, inflight: app.inflight };
  }

  async sweepIdle() {
    const now = Date.now();
    for (const app of this.apps.values()) {
      if (app.state === "ready" && app.inflight === 0 && app.lastUsed && now - app.lastUsed > this.idleSeconds * 1000) {
        await this.sleep(app, "idle");
        this.log(app, "info", "runtime", null, app.releaseId, "application went to sleep after idle timeout");
      }
    }
  }

  snapshot() {
    return [...this.apps.values()]
      .filter((a) => a.assetId)
      .map((a) => ({
        asset_id: a.assetId,
        environment: a.environment,
        state: a.state,
        inflight: a.inflight,
        queued: this.runners.queuedFor(a.key),
        last_used_at: a.lastUsed ? new Date(a.lastUsed).toISOString() : null,
        open_connections: this.pools.stats(a.key).open,
        last_error_code: a.lastErrorCode,
        last_error_at: a.lastErrorAt,
        breaker_open_until: a.breakerOpenUntil > Date.now() ? new Date(a.breakerOpenUntil).toISOString() : null,
      }));
  }

  drainLogs() {
    const out = this.logs;
    this.logs = [];
    return out;
  }
}
