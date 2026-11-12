// What ICS reads when it renders an app as a document: the records a person's
// list rules allow, and the app's own document view run as that person.
import { test } from "node:test";
import assert from "node:assert/strict";
import { Model } from "../src/broker/model.js";
import { exportData } from "../src/broker/export.js";
import { Gateway } from "../src/broker/gateway.js";

// Self-contained: the runtime image has no backend sources.
const manifest = {
  database: {
    collections: {
      notes: {
        fields: { text: { type: "string", required: true, maxLength: 2000 } },
        crud: { list: { permission: "notes.read", rowScope: "own" }, get: { permission: "notes.read", rowScope: "own" } },
      },
    },
  },
  capabilities: {},
  endpoints: [],
  permissions: { "notes.read": { label: "Read notes" } },
  roles: { reader: { label: "Reader", permissions: ["notes.read"] } },
};

function gatewayWith(permissions, state = "enabled") {
  const calls = [];
  return {
    calls,
    ics: { authorize: async () => ({ found: true, app_use: true, user: { id: "u1" }, desired_state: state, release: { id: "r1" }, permissions }) },
    apps: { get: () => ({}), sync: async () => {}, model: async () => ({ bundle: {}, model: new Model(manifest, "a_x") }) },
    read: async (rc, fn) => {
      calls.push([...rc.permissions]);
      return { items: [{ id: "n1", text: "hello" }], nextCursor: "c2" };
    },
  };
}

test("a collection is exported only with its list permission", async () => {
  const out = await exportData(gatewayWith(["notes.read"]), { assetHex: "a".repeat(32), environment: "prod", userId: "u1" });
  assert.deepEqual(out.collections, [{ name: "notes", readable: true, items: [{ id: "n1", text: "hello" }], next_cursor: "c2" }]);
  const none = await exportData(gatewayWith([]), { assetHex: "a".repeat(32), environment: "prod", userId: "u1" });
  assert.deepEqual(none.collections, [{ name: "notes", readable: false, permission: "notes.read" }]);
});

test("a suspended app exports nothing", async () => {
  await assert.rejects(exportData(gatewayWith(["notes.read"], "suspended"), { assetHex: "a".repeat(32), environment: "prod", userId: "u1" }), (e) => e.code === "app_suspended");
});

// ---------- the app's document view ----------

const withView = {
  ...manifest,
  capabilities: { "notes.list_own": { collection: "notes", operation: "list", permission: "notes.read", rowScope: "own", readFields: ["id", "text"] } },
  endpoints: [{
    name: "document", method: "GET", path: "/v1/custom/document", handler: "handlers/document.mjs#default", permission: "notes.read",
    transaction: "read_only", ifMatch: "none", idempotency: "none", capabilities: ["notes.list_own"],
    input: { query: { type: "object", additionalProperties: false, properties: {} } },
    output: { type: "object", additionalProperties: false, required: ["markdown"], properties: { markdown: { type: "string" } } },
  }],
  document: { endpoint: "document" },
};

function docGateway(permissions, { m = withView, out = { status: 200, body: { markdown: "# Notes\n\n- hello" } } } = {}) {
  const g = new Gateway({ config: { sessionSecret: "s" }, ics: null, apps: null, pools: null, runners: null });
  const runs = [];
  g.ics = { authorize: async (hex, env, userId) => ({ found: true, app_use: true, user: { id: userId }, desired_state: "enabled", release: { id: "r1" }, permissions }) };
  g.apps = { get: () => ({ key: "k" }), sync: async () => {}, breakerOpen: () => false, model: async () => ({ bundle: { manifest: m }, model: new Model(m, "a_x") }) };
  g.runReadOnly = async (rc, endpoint, input) => {
    runs.push({ user: rc.auth.user.id, endpoint: endpoint.name, input, permissions: [...rc.permissions] });
    return out;
  };
  return { g, runs };
}

const VIEW = { assetHex: "a".repeat(32), environment: "prod", userId: "u7", document: true };

test("the document view runs the declared endpoint as the reader, with the data", async () => {
  const { g, runs } = docGateway(["notes.read"]);
  g.read = async () => ({ items: [], nextCursor: null });
  const out = await exportData(g, VIEW);
  assert.deepEqual(out.document, { markdown: "# Notes\n\n- hello" });
  assert.equal(out.collections[0].name, "notes");
  assert.deepEqual(runs, [{ user: "u7", endpoint: "document", input: { params: {}, query: {}, body: null }, permissions: ["notes.read"] }]);
  // Only when asked for.
  runs.length = 0;
  assert.equal((await exportData(g, { ...VIEW, document: false })).document, undefined);
  assert.equal(runs.length, 0);
});

test("without the endpoint's permission the view is forbidden, the data still comes", async () => {
  const { g, runs } = docGateway([]);
  const out = await exportData(g, VIEW);
  assert.deepEqual(out.document, { error: "forbidden" });
  assert.deepEqual(out.collections, [{ name: "notes", readable: false, permission: "notes.read" }]);
  assert.equal(runs.length, 0);
});

test("an app without a document view has none; a failing view reports its code", async () => {
  const plain = docGateway(["notes.read"], { m: manifest });
  plain.g.read = async () => ({ items: [], nextCursor: null });
  assert.equal((await exportData(plain.g, VIEW)).document, undefined);
  const broken = docGateway(["notes.read"], { out: { status: 200, body: { text: "no markdown" } } });
  broken.g.read = async () => ({ items: [], nextCursor: null });
  assert.deepEqual((await exportData(broken.g, VIEW)).document, { error: "document_view_failed" });
});

test("the document view checks capabilities per data call; other endpoints up front", async () => {
  const { g } = docGateway(["notes.read"]);
  const rc = { permissions: new Set(["notes.read"]), bundle: { manifest: withView }, model: new Model(withView, "a_x"), app: {} };
  const other = { ...withView.endpoints[0], name: "other", capabilities: ["missing.cap"] };
  assert.throws(() => g.prepareCustom(rc, other), (e) => e.status === 403);
  g.prepareCustom(rc, { ...withView.endpoints[0], capabilities: ["missing.cap"] });
  assert.ok(rc.limits.wallMs > 0);
});
