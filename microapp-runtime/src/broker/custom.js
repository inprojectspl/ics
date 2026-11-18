// Execution of a custom endpoint: one runner slot, one transaction on one
// client, every SDK call checked against the endpoint's declared
// capabilities and replayed by the broker as controlled SQL. The handler
// result counts only after its output validated and no call is pending.
import { BREAKER_CODES } from "./apps.js";
import * as data from "./data.js";
import { DataError } from "./data.js";
import { mapPgError } from "./db.js";
import { HttpError } from "./http.js";
import { validate } from "./validate.js";

export async function invokeHandler(gw, rc, endpoint, input, ifRevision, client, ctx, limits) {
  const { bundle, model, app } = rc;
  const [file] = endpoint.handler.split("#");
  const code = bundle.handlers[file];
  if (typeof code !== "string") throw new HttpError(500, "handler_missing", "handler code missing in release");
  const deadline = Date.now() + limits.wallMs;
  const leaseKey = `${app.key}|${rc.auth.release.id}|${rc.auth.policy_generation}`;
  const slot = await gw.runners.acquire(app.key, leaseKey, Math.min(deadline, Date.now() + limits.queueMs));
  let recycle = false;
  let reason;
  let dbCalls = 0;
  let chain = Promise.resolve();
  let inflightRpc = 0;
  let rpcFailure = null;
  const readOps = new Set(["get", "list", "count", "groupCount"]);
  const allowed = new Set(endpoint.capabilities);
  const handleRpc = async (method, args) => {
    if (method.startsWith("db.")) {
      dbCalls += 1;
      if (dbCalls > limits.maxDbCalls) throw new DataError(429, "db_call_limit", "too many data operations in one request");
      const op = method.slice(3);
      const [collectionName, ...rest] = args;
      const options = (rest[rest.length - 1] && typeof rest[rest.length - 1] === "object" && !Array.isArray(rest[rest.length - 1]) ? rest[rest.length - 1] : {}) ?? {};
      const capName = options.capability;
      if (typeof capName !== "string" || !allowed.has(capName)) throw new DataError(403, "capability_not_declared", "the endpoint did not declare this capability");
      if (endpoint.transaction === "read_only" && !readOps.has(op)) throw new DataError(403, "read_only_transaction", "this endpoint may only read");
      const opName = op === "delete" ? "delete" : op;
      const r = data.capabilityRule(model, capName, opName);
      data.assertPermission(r, rc.permissions);
      if (r.collection !== collectionName) throw new DataError(403, "capability_collection_mismatch", "capability is for another collection");
      const collection = model.collection(collectionName);
      // The revision for writes comes from the checked If-Match header
      // unless the handler names another record's revision explicitly.
      switch (op) {
        case "get": {
          const lockRule = options.forUpdate && endpoint.transaction === "required" ? { ...r, lock: true } : r;
          return data.get(client, ctx, collection, lockRule, rest[0]);
        }
        case "list":
          return data.list(client, ctx, collection, r, rest[0] ?? {});
        case "insert":
          return data.insert(client, ctx, collection, r, rest[0]);
        case "update":
          return data.update(client, ctx, collection, r, rest[0], rest[1], options.ifRevision);
        case "delete":
          await data.remove(client, ctx, collection, r, rest[0], options.ifRevision);
          return null;
        case "count":
          return data.count(client, ctx, collection, r, rest[0] ?? []);
        case "groupCount":
          return data.groupCount(client, ctx, collection, r, rest[0], rest[1] ?? []);
        default:
          throw new DataError(400, "unknown_operation", "unknown data operation");
      }
    }
    throw new DataError(400, "unknown_operation", "unknown host call");
  };
  try {
    await slot.ensureLease(leaseKey);
    const context = {
      // What the caller may do, so a handler (a document view above all)
      // can leave out what this person cannot see; every data call is still
      // checked against these permissions.
      actor: { id: rc.auth.user.id, permissions: [...rc.permissions].sort(), roles: rc.auth.roles ?? [] },
      app: { id: rc.auth.asset_id, environment: rc.target.environment, release: rc.auth.release.id, dataGeneration: rc.auth.data_generation },
      request: { id: rc.requestId, deadline: new Date(deadline).toISOString(), preconditions: { revision: ifRevision ?? null } },
    };
    const { reqId, promise } = slot.run(
      "invoke",
      { code, filename: file, input, context, limits: { memoryBytes: limits.memoryBytes, cpuMs: limits.cpuMs, wallMs: Math.max(1, deadline - Date.now()), stackBytes: limits.stackBytes } },
      {
        onRpc: (callId, method, args) => {
          inflightRpc += 1;
          // One client, one transaction: handler calls run strictly in order.
          chain = chain.then(async () => {
            try {
              const value = await handleRpc(method, Array.isArray(args) ? args : []);
              slot.rpcResult(reqId, callId, { ok: true, value });
            } catch (err) {
              const e = err?.code === "validation_failed" ? err : err instanceof DataError || err instanceof HttpError ? err : mapPgError(err);
              if (!(e instanceof DataError || e instanceof HttpError || e.code === "validation_failed") || e.status >= 500) {
                rpcFailure = e;
              }
              slot.rpcResult(reqId, callId, { ok: false, error: { code: e.code, message: e.message, status: e.status ?? 422, field: e.pointer } });
            } finally {
              inflightRpc -= 1;
            }
          });
        },
        onLog: (args) => {
          const [level, message, fields] = Array.isArray(args) ? args : [];
          gw.apps.log(app, ["info", "warn", "error"].includes(level) ? level : "info", "handler", rc.requestId, rc.auth.release.id, String(message ?? "").slice(0, 500), fields && typeof fields === "object" ? fields : {});
        },
      },
    );
    const timeout = new Promise((_, reject) => {
      const t = setTimeout(() => reject(new DataError(504, "execution_deadline", "handler exceeded its deadline")), Math.max(0, deadline - Date.now()));
      t.unref();
      promise.finally(() => clearTimeout(t));
    });
    const result = await Promise.race([promise, timeout]);
    await chain;
    if (rpcFailure) throw rpcFailure;
    if (!result.ok) {
      const code = result.error?.code ?? "handler_error";
      if (BREAKER_CODES.has(code) || code === "handler_stalled") {
        recycle = true;
        reason = code;
        gw.apps.recordFailure(app, rc.auth.release.id, code, rc.requestId);
        throw new DataError(code === "memory_limit" ? 507 : 504, code, "the handler was stopped");
      }
      const g = result.error?.guest;
      if (g && Number.isInteger(g.status) && [400, 403, 404, 409, 412, 422].includes(g.status)) {
        throw new DataError(g.status, g.code ?? "handler_rejected", g.message);
      }
      gw.apps.recordFailure(app, rc.auth.release.id, code);
      gw.apps.log(app, "error", "handler", rc.requestId, rc.auth.release.id, "handler failed", { code, message: result.error?.message });
      throw new DataError(500, "handler_failed", "the handler failed");
    }
    if (result.pendingRpc > 0 || inflightRpc > 0) {
      throw new DataError(500, "unsettled_operation", "the handler returned while a data operation was still running");
    }
    const out = result.value;
    if (!out || typeof out !== "object" || !Number.isInteger(out.status) || out.status < 200 || out.status > 299) {
      throw new DataError(500, "handler_output_invalid", "the handler must return {status, body} with a 2xx status");
    }
    const size = Buffer.byteLength(JSON.stringify(out.body ?? null));
    if (size > limits.maxResponseBytes) throw new DataError(500, "response_too_large", "the handler response is too large");
    try {
      if (out.status !== 204) validate(endpoint.output, out.body, "");
    } catch (err) {
      throw new DataError(500, "handler_output_invalid", `the handler output does not match the declared schema at ${err.pointer || "/"}`);
    }
    return { status: out.status, body: out.status === 204 ? undefined : out.body };
  } catch (err) {
    if (err?.code === "execution_deadline") {
      recycle = true;
      reason = "execution_deadline";
    }
    throw err;
  } finally {
    gw.runners.release(slot, { recycle, reason });
  }
}
