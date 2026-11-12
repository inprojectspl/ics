// Broker admin API on the private network (ICS -> broker): drain on
// suspend, sleep, restart, handler syntax checks and a status snapshot.
// Authenticated with the same service token; never exposed by the proxy.
import crypto from "node:crypto";
import { exportData } from "./export.js";
import { checkRows, checkValues } from "./model.js";

function safeEqual(a, b) {
  const x = Buffer.from(String(a ?? ""));
  const y = Buffer.from(String(b ?? ""));
  return x.length === y.length && crypto.timingSafeEqual(x, y);
}

async function body(req) {
  const chunks = [];
  let size = 0;
  for await (const c of req) {
    size += c.length;
    if (size > 2 * 1024 * 1024) throw Object.assign(new Error("too large"), { status: 413 });
    chunks.push(c);
  }
  const text = Buffer.concat(chunks).toString();
  return text ? JSON.parse(text) : {};
}

function json(res, status, value) {
  res.writeHead(status, { "content-type": "application/json", "cache-control": "no-store" });
  res.end(JSON.stringify(value));
}

export function adminHandler({ config, apps, runners, gateway, incarnation }) {
  return async (req, res) => {
    try {
      if (!safeEqual(req.headers["x-ics-service-token"], config.serviceToken)) return json(res, 401, { code: "unauthorized" });
      const url = new URL(req.url, "http://broker");
      const m = /^\/admin\/apps\/([0-9a-f]{32})\/(prod)\/(sleep|suspend|restart)$/.exec(url.pathname);
      if (m && req.method === "POST") {
        const app = apps.get(m[1], m[2]);
        if (m[3] === "suspend") return json(res, 200, await apps.drain(app));
        if (m[3] === "sleep") {
          const idle = await apps.waitIdle(app, 5000);
          await apps.sleep(app, "sleep");
          return json(res, 200, { drained: idle, inflight: app.inflight });
        }
        // restart: drain in-flight work, close pools, recycle runner processes
        const idle = await apps.waitIdle(app, 5000);
        await apps.sleep(app, "restart");
        app.blocked = false;
        return json(res, 200, { drained: idle, inflight: app.inflight });
      }
      const exp = /^\/admin\/apps\/([0-9a-f]{32})\/(prod)\/export$/.exec(url.pathname);
      if (exp && req.method === "POST") {
        const { user_id: userId, collection, limit, cursor, document } = await body(req);
        if (typeof userId !== "string") return json(res, 400, { code: "bad_request", detail: "user_id required" });
        const n = Number(limit ?? 50);
        if (!Number.isInteger(n) || n < 1 || n > 200) return json(res, 400, { code: "bad_request", detail: "limit 1..200" });
        return json(res, 200, await exportData(gateway, { assetHex: exp[1], environment: exp[2], userId, only: collection ?? null, limit: n, cursor: cursor ?? null, document: document === true }));
      }
      if (url.pathname === "/admin/compile" && req.method === "POST") {
        const { files, seeds, values, fields } = await body(req);
        const results = files && Object.keys(files).length ? await compileAll(runners, files) : {};
        const rows = Object.fromEntries(Object.entries(seeds ?? {}).map(([path, s]) => [path, checkRows(s.fields, s.rows)]));
        // Manifest values name their field by pointer; each field is sent once.
        const stated = (values ?? []).map((v) => ({ ...v, field: fields?.[v.field] }));
        return json(res, 200, { results, seeds: rows, values: checkValues(stated) });
      }
      if (url.pathname === "/admin/status" && req.method === "GET") {
        return json(res, 200, { incarnation, apps: apps.snapshot(), slots: runners.snapshot() });
      }
      return json(res, 404, { code: "not_found" });
    } catch (err) {
      return json(res, err.status ?? 500, { code: err.code ?? "admin_failed", detail: String(err.message) });
    }
  };
}

async function compileAll(runners, files) {
  const key = `compile|${crypto.randomUUID()}`;
  const slot = await runners.acquire(key, key, Date.now() + 3000);
  const results = {};
  try {
    await slot.ensureLease(key);
    for (const [path, code] of Object.entries(files)) {
      const { promise } = slot.run("compile", { code, filename: path }, { onRpc: () => {}, onLog: () => {} });
      const r = await Promise.race([promise, new Promise((resolve) => setTimeout(() => resolve({ ok: false, error: { code: "compile_timeout" } }), 3000).unref())]);
      results[path] = r.ok ? { ok: true } : { ok: false, code: r.error?.code ?? "syntax_error", message: r.error?.message };
    }
  } finally {
    // Compiling author code never leaves a child behind for a real lease.
    runners.release(slot, { recycle: true, reason: "compile" });
  }
  return results;
}
