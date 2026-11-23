// The broker side of a Google Sheets link: reads under the list rule, applies
// accepted changes as the person, all or nothing, once per operation key.
import { test } from "node:test";
import assert from "node:assert/strict";
import { Model } from "../src/broker/model.js";
import { MAX_CHANGES, MAX_ROWS, applyChanges, applyDeadlineMs, readRows } from "../src/broker/sheets.js";
import { Gateway } from "../src/broker/gateway.js";
import { AppRegistry } from "../src/broker/apps.js";

const manifest = {
  database: {
    collections: {
      bookings: {
        fields: { room: { type: "string", maxLength: 100 }, note: { type: "string", maxLength: 500 }, secret: { type: "string" } },
        crud: {
          list: { permission: "b.read", rowScope: "all", readFields: ["id", "revision", "room", "note"] },
          update: { permission: "b.write", rowScope: "all", writeFields: ["room", "note"] },
          create: { permission: "b.write", rowScope: "all", writeFields: ["room", "note"] },
        },
      },
    },
  },
  capabilities: {},
  endpoints: [],
  permissions: { "b.read": { label: "Read" }, "b.write": { label: "Write" } },
  roles: { editor: { label: "Editor", permissions: ["b.read", "b.write"] } },
};

const ID1 = "00000000-0000-4000-8000-000000000001";
const ID2 = "00000000-0000-4000-8000-000000000002";

function fakeDb() {
  const idem = new Map();
  const queries = [];
  let failUpdate = false;
  const client = {
    async query(text, params = []) {
      queries.push(text);
      if (/^(BEGIN|SET LOCAL|COMMIT|ROLLBACK)/.test(text)) return { rows: [], rowCount: 0 };
      if (text.startsWith("DELETE FROM") && text.includes("_ics_idempotency")) return { rows: [], rowCount: 0 };
      if (text.startsWith("INSERT INTO") && text.includes("_ics_idempotency")) {
        const k = params.slice(0, 4).join("|");
        if (idem.has(k)) return { rows: [], rowCount: 0 };
        idem.set(k, { request_hash: params[4], response: null, pending: true });
        client.reservedKey = k;
        return { rows: [{ key: params[3] }], rowCount: 1 };
      }
      if (text.startsWith("SELECT request_hash")) return { rows: [idem.get(params.slice(0, 4).join("|"))] };
      if (text.startsWith("UPDATE") && text.includes("_ics_idempotency")) {
        idem.get(params.slice(0, 4).join("|")).staged = { status: params[4], response: JSON.parse(params[5]) };
        return { rows: [], rowCount: 1 };
      }
      if (text.startsWith("UPDATE")) {
        if (failUpdate) return { rows: [], rowCount: 0 };
        return { rows: [{ id: ID1, revision: 3 }], rowCount: 1 };
      }
      if (text.startsWith("SELECT revision")) return { rows: [{ revision: 5 }] };
      if (text.startsWith("INSERT INTO") && text.includes("_ics_audit")) return { rows: [], rowCount: 1 };
      if (text.startsWith("INSERT INTO")) return { rows: [{ id: params[0], revision: 1 }], rowCount: 1 };
      throw new Error(`unexpected ${text}`);
    },
    release() {},
  };
  return {
    idem,
    queries,
    client,
    set failUpdate(v) { failUpdate = v; },
    // Commit makes the staged response visible; a rollback drops the key.
    pools: { connect: async () => client },
    settle(committed) {
      for (const [k, v] of idem) {
        if (!v.pending) continue;
        if (committed) idem.set(k, { request_hash: v.request_hash, ...v.staged, headers: {} });
        else idem.delete(k);
      }
    },
  };
}

function gatewayWith(db, permissions) {
  // The registry's own counters, state and change list; ICS-facing parts stubbed.
  const registry = new AppRegistry({ ics: null, pools: null, runners: null, idleSeconds: 600 });
  const app = registry.get("a".repeat(32), "prod");
  const gw = {
    ics: { authorize: async () => ({ found: true, app_use: true, user: { id: "u1" }, asset_id: "a", data_generation: 1, desired_state: "enabled", release: { id: "r1" }, permissions, credential_generation: 1 }) },
    apps: {
      registry,
      get: () => app,
      sync: async () => {},
      model: async () => ({ bundle: { manifest }, model: new Model(manifest, "a_x") }),
      binding: async () => ({ schema: "a_x" }),
      begin: (a, use) => registry.begin(a, use),
      end: (a, use) => registry.end(a, use),
      markChanged: (a, names, origin) => registry.markChanged(a, names, origin),
      recordFailure() {},
    },
    pools: db.pools,
    config: { sessionSecret: "s".repeat(32) },
    ctxFor(rc, binding) {
      return { assetId: "a", environment: "prod", dataGeneration: 1, actorId: "u1", requestId: rc.requestId, releaseId: "r1", schema: binding.schema, cursorSecret: "s".repeat(32), dataFull: false };
    },
  };
  gw.transact = Gateway.prototype.transact;
  gw.read = async (rc, fn) => fn({ query: async () => ({ rows: [{ id: ID1, revision: 2, room: "A", note: null }] }) }, gw.ctxFor(rc, { schema: "a_x" }));
  return gw;
}

const target = { assetHex: "a".repeat(32), environment: "prod", userId: "u1", collection: "bookings" };

async function apply(db, gw, changes, key = "op-00000001", release = "r1") {
  try {
    const out = await applyChanges(gw, { ...target, key, changes, release });
    db.settle(true);
    return out;
  } catch (e) {
    db.settle(false);
    throw e;
  }
}

test("rows come with id, revision and only the linked fields", async () => {
  const out = await readRows(gatewayWith(fakeDb(), ["b.read"]), { ...target, fields: ["room", "note"] });
  assert.deepEqual(out.rows, [{ id: ID1, revision: 2, room: "A", note: null }]);
  assert.equal(out.truncated, false);
});

test("a field the list rule hides cannot be linked", async () => {
  await assert.rejects(readRows(gatewayWith(fakeDb(), ["b.read"]), { ...target, fields: ["secret"] }), (e) => e.code === "field_not_readable");
});

test("without the list permission nothing is read", async () => {
  await assert.rejects(readRows(gatewayWith(fakeDb(), []), { ...target, fields: ["room"] }), (e) => e.code === "forbidden");
});

test("changes apply once; the same key replays the stored result", async () => {
  const db = fakeDb();
  const gw = gatewayWith(db, ["b.read", "b.write"]);
  const changes = [{ op: "update", id: ID1, revision: 2, patch: { room: "B" } }, { op: "create", id: ID2, data: { room: "C" } }];
  const first = await apply(db, gw, changes);
  assert.equal(first.replayed, false);
  assert.equal(first.results[0].revision, 3);
  // ICS names the record it creates, so it can match it with its sheet row.
  assert.equal(first.results[1].id, ID2);
  const writes = db.queries.filter((q) => /^(UPDATE "a_x"\."bookings"|INSERT INTO "a_x"\."bookings")/.test(q)).length;
  const again = await apply(db, gw, changes);
  assert.equal(again.replayed, true);
  assert.deepEqual(again.results, first.results);
  assert.equal(db.queries.filter((q) => /^(UPDATE "a_x"\."bookings"|INSERT INTO "a_x"\."bookings")/.test(q)).length, writes);
  await assert.rejects(apply(db, gw, [changes[0]]), (e) => e.code === "idempotency_key_reused");
});

test("a stale revision rolls back the whole operation and names the change", async () => {
  const db = fakeDb();
  db.failUpdate = true;
  const gw = gatewayWith(db, ["b.read", "b.write"]);
  await assert.rejects(
    apply(db, gw, [{ op: "create", id: ID2, data: { room: "C" } }, { op: "update", id: ID1, revision: 2, patch: { room: "B" } }]),
    (e) => e.code === "revision_mismatch" && e.change === 1 && e.currentRevision === 5,
  );
  assert.ok(db.queries.includes("ROLLBACK"));
  assert.equal(db.idem.size, 0);
});

test("a field outside the write rule is refused", async () => {
  const db = fakeDb();
  await assert.rejects(apply(db, gatewayWith(db, ["b.read", "b.write"]), [{ op: "update", id: ID1, revision: 2, patch: { secret: "x" } }]), (e) => e.code === "validation_failed" && e.change === 0);
});

test("without the write permission nothing is applied", async () => {
  const db = fakeDb();
  await assert.rejects(apply(db, gatewayWith(db, ["b.read"]), [{ op: "update", id: ID1, revision: 2, patch: { room: "B" } }]), (e) => e.code === "forbidden");
});

test("a preview made under another release is not applied", async () => {
  const db = fakeDb();
  await assert.rejects(apply(db, gatewayWith(db, ["b.read", "b.write"]), [{ op: "update", id: ID1, revision: 2, patch: { room: "B" } }], "op-00000002", "r0"), (e) => e.code === "release_changed");
  assert.equal(db.idem.size, 0);
});

test("only the linked fields of each page stay in memory", async () => {
  const out = await readRows(gatewayWith(fakeDb(), ["b.read"]), { ...target, fields: ["room"] });
  assert.deepEqual(out.rows, [{ id: ID1, revision: 2, room: "A" }]);
});

test("the owner's row limit cuts the read and says so", async () => {
  const out = await readRows(gatewayWith(fakeDb(), ["b.read"]), { ...target, fields: ["room"], limit: 0 });
  assert.equal(out.truncated, true);
  assert.deepEqual(out.rows, []);
});

test("ICS's reads and writes count as in-flight work but neither wake the app nor keep it awake", async () => {
  const db = fakeDb();
  const gw = gatewayWith(db, ["b.read", "b.write"]);
  const app = gw.apps.get();
  const inflight = [];
  const connect = db.pools.connect;
  db.pools.connect = async () => {
    inflight.push(app.inflight);
    return connect();
  };
  await apply(db, gw, [{ op: "update", id: ID1, revision: 2, patch: { room: "B" } }]);
  gw.read = Gateway.prototype.read;
  gw.pools = {
    connect: async () => {
      inflight.push(app.inflight);
      return { query: async (text) => (text.startsWith("SELECT") ? { rows: [{ id: ID1, revision: 3, room: "B", note: null }] } : { rows: [] }), release() {} };
    },
  };
  assert.equal((await readRows(gw, { ...target, fields: ["room"] })).rows[0].room, "B");
  // The drain barrier still waits for them.
  assert.deepEqual(inflight, [1, 1]);
  assert.equal(app.inflight, 0);
  assert.equal(app.state, "sleeping");
  assert.equal(app.lastUsed, null);
  // A person's request is use.
  gw.apps.begin(app);
  gw.apps.end(app);
  assert.equal(app.state, "ready");
  assert.ok(app.lastUsed);
});

test("the sync's own writes reach realtime watchers but not the report to ICS", async () => {
  const db = fakeDb();
  const gw = gatewayWith(db, ["b.read", "b.write"]);
  const heard = [];
  gw.apps.registry.realtime = { changed: (a, names) => heard.push([...names]) };
  const app = gw.apps.get();
  await apply(db, gw, [{ op: "update", id: ID1, revision: 2, patch: { room: "B" } }]);
  assert.deepEqual(heard, [["bookings"]]);
  assert.equal(app.changed.size, 0, "a report would start a sync of the same link again");
  gw.apps.markChanged(app, ["bookings"], "PATCH /v1/collections/bookings/:id");
  assert.deepEqual([...app.changed], ["bookings"]);
});

test("one apply takes a whole first sync, with a deadline that grows with it", () => {
  assert.equal(MAX_CHANGES, MAX_ROWS);
  assert.equal(applyDeadlineMs(1), 20_020);
  assert.ok(applyDeadlineMs(5000) > applyDeadlineMs(1000));
  assert.equal(applyDeadlineMs(MAX_CHANGES), 300_000);
});
