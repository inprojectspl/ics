// Connection pools keyed by (asset, environment, role, credential generation).
// Every physical connection logs in with that asset's runtime role; there is
// no shared login with SET ROLE. Pools are created on demand (min 0, max 2)
// and one global budget counts every client of every pool: open, idle and
// still handshaking (pg-pool lists a client as soon as it starts connecting).
import pg from "pg";
import { DataError } from "./data.js";

// Plain JSON values out of the database: dates and timestamps as ISO text,
// numeric as text (decimal), bigint as a safe JS number.
pg.types.setTypeParser(1082, (v) => v);
pg.types.setTypeParser(1184, (v) => new Date(v).toISOString());
pg.types.setTypeParser(1114, (v) => new Date(`${v}Z`).toISOString());
pg.types.setTypeParser(20, (v) => {
  const n = Number(v);
  return Number.isSafeInteger(n) ? n : v;
});

export class PoolRegistry {
  constructor({ maxConnections, perAppMax = 2, idleMs = 10000 }) {
    this.maxConnections = maxConnections;
    this.perAppMax = perAppMax;
    this.idleMs = idleMs;
    this.pools = new Map(); // key -> { pool, open, lastUsed, appKey }
  }

  /** Clients counted against the budget, handshakes included. */
  get used() {
    let n = 0;
    for (const entry of this.pools.values()) n += entry.pool.totalCount;
    return n;
  }

  key(binding) {
    return `${binding.asset_id}:${binding.environment}:${binding.user}:${binding.credential_generation}`;
  }

  stats(appKey) {
    let open = 0;
    for (const entry of this.pools.values()) if (entry.appKey === appKey) open += entry.open;
    return { open };
  }

  get(appKey, binding) {
    const key = this.key(binding);
    let entry = this.pools.get(key);
    if (entry) return entry;
    // A newer credential generation retires every older pool of the app.
    for (const [k, e] of this.pools) if (e.appKey === appKey) this.#close(k, e);
    const pool = new pg.Pool({
      host: binding.host,
      port: binding.port,
      database: binding.database,
      user: binding.user,
      password: binding.password,
      max: this.perAppMax,
      idleTimeoutMillis: this.idleMs,
      connectionTimeoutMillis: 2000,
      application_name: "ics-microapp-broker",
      allowExitOnIdle: true,
    });
    entry = { pool, open: 0, lastUsed: Date.now(), appKey, schema: binding.schema };
    pool.on("connect", () => {
      entry.open += 1;
    });
    pool.on("remove", () => {
      entry.open -= 1;
    });
    pool.on("error", () => {
      // An idle client died (server restart, terminate); the pool drops it.
    });
    this.pools.set(key, entry);
    return entry;
  }

  /** Free budget by closing pools of other apps that have no busy client. */
  #reclaim(exceptKey) {
    for (const [k, e] of this.pools) {
      if (k === exceptKey) continue;
      if (e.pool.waitingCount === 0 && e.pool.idleCount === e.pool.totalCount && e.pool.totalCount > 0) {
        this.#close(k, e);
        if (this.used < this.maxConnections) return true;
      }
    }
    return this.used < this.maxConnections;
  }

  async connect(appKey, binding) {
    const entry = this.get(appKey, binding);
    entry.lastUsed = Date.now();
    const needsNew = entry.pool.idleCount === 0 && entry.pool.totalCount < this.perAppMax;
    if (needsNew && this.used >= this.maxConnections && !this.#reclaim(this.key(binding))) {
      throw new DataError(503, "capacity_exhausted", "no database connection budget left", { retryAfter: 1 });
    }
    // pool.connect() lists the new client synchronously, so the next caller
    // already counts this handshake.
    try {
      return await entry.pool.connect();
    } catch (err) {
      if (/timeout/i.test(err.message)) throw new DataError(503, "capacity_exhausted", "database connection timed out", { retryAfter: 1 });
      throw new DataError(503, "database_unavailable", "database unavailable");
    }
  }

  closeApp(appKey) {
    for (const [k, e] of this.pools) if (e.appKey === appKey) this.#close(k, e);
  }

  #close(key, entry) {
    this.pools.delete(key);
    entry.pool.end().catch(() => {});
  }
}

/**
 * Run `fn(client)` in one transaction on one client. A failed ROLLBACK or a
 * deadline means the connection is destroyed rather than returned: the
 * server then aborts whatever transaction it still holds.
 */
export async function inTransaction(registry, appKey, binding, { readOnly, snapshot, statementTimeoutMs, signal }, fn) {
  const client = await registry.connect(appKey, binding);
  let destroy = false;
  const onAbort = () => {
    destroy = true;
    // Closing the socket is the cancel that cannot lose a race with COMMIT:
    // PostgreSQL rolls back a transaction whose connection is gone.
    client.connection?.stream?.destroy();
  };
  signal?.addEventListener("abort", onAbort, { once: true });
  try {
    // `snapshot`: every statement sees the database as of the first one, so
    // reads of several tables agree with each other.
    await client.query(readOnly ? (snapshot ? "BEGIN READ ONLY ISOLATION LEVEL REPEATABLE READ" : "BEGIN READ ONLY") : "BEGIN");
    await client.query(`SET LOCAL statement_timeout = ${Math.max(100, Math.floor(statementTimeoutMs))}`);
    const result = await fn(client);
    if (signal?.aborted) throw new DataError(504, "execution_deadline", "request deadline exceeded");
    try {
      await client.query("COMMIT");
    } catch (err) {
      destroy = true;
      // The server may or may not have committed: only the idempotency
      // record can tell, on a retry with the same key.
      throw new DataError(504, "commit_unknown", "the outcome of the commit is unknown; retry with the same Idempotency-Key", { cause: err });
    }
    return result;
  } catch (err) {
    if (!destroy) {
      try {
        await client.query("ROLLBACK");
      } catch {
        destroy = true;
      }
    }
    if (signal?.aborted && !(err instanceof DataError && err.code === "commit_unknown")) {
      throw new DataError(504, "execution_deadline", "request deadline exceeded");
    }
    throw mapPgError(err);
  } finally {
    signal?.removeEventListener("abort", onAbort);
    client.release(destroy);
  }
}

export function mapPgError(err) {
  // Gateway and data errors carry an HTTP status; only driver errors
  // (SQLSTATE codes) need mapping.
  if (err instanceof DataError || err?.code === "validation_failed" || Number.isInteger(err?.status)) return err;
  switch (err?.code) {
    case "23514": // check_violation
    case "23502": // not_null_violation
    case "22001": // string too long
    case "22003": // numeric out of range
    case "22P02": // invalid text representation
    case "22007":
    case "22008":
      return new DataError(422, "validation_failed", "a value violates the data model");
    case "23505":
      return new DataError(409, "unique_violation", "a record with this value already exists");
    case "23503":
      return new DataError(409, "reference_violation", "the referenced record does not exist");
    case "40001":
    case "40P01":
      return new DataError(409, "serialization_conflict", "concurrent change, retry");
    case "57014":
      return new DataError(504, "execution_deadline", "statement timeout");
    case "55P03":
      return new DataError(409, "lock_timeout", "the record is locked by another request");
    case "42501":
      return new DataError(403, "forbidden", "database permission denied");
    default:
      return new DataError(500, "internal_error", "data operation failed", { cause: err });
  }
}
