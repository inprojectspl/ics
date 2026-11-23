// A list rule's readFields bound what a caller may learn: no filter, sort or
// cursor may reveal a field the rule hides.
import { test } from "node:test";
import assert from "node:assert/strict";
import { Model } from "../src/broker/model.js";
import * as data from "../src/broker/data.js";

const manifest = {
  database: {
    collections: {
      people: {
        fields: { name: { type: "string", required: true, maxLength: 200 }, salary: { type: "integer" } },
        crud: { list: { permission: "people.read", rowScope: "all", readFields: ["id", "name"] } },
      },
    },
  },
  capabilities: {},
  endpoints: [],
  permissions: { "people.read": { label: "Read" } },
  roles: { reader: { label: "Reader", permissions: ["people.read"] } },
};

const model = new Model(manifest, "a_x");
const collection = model.collections.get("people");
const rule = data.crudRule(collection, "list");
const ctx = { actorId: "u1", assetId: "a", environment: "prod", dataGeneration: 1, cursorSecret: "s".repeat(32) };

function client(rows) {
  const queries = [];
  return { queries, query: async (text, params) => (queries.push({ text, params }), { rows }) };
}

test("filtering by a hidden field is refused", async () => {
  await assert.rejects(
    data.list(client([]), ctx, collection, rule, { filters: [{ field: "salary", op: "gt", value: 100 }] }),
    (e) => e.pointer === "/filters/0/field",
  );
});

test("sorting by a hidden field is refused", async () => {
  await assert.rejects(data.list(client([]), ctx, collection, rule, { sort: "-salary" }), (e) => e.pointer === "/sort");
});

test("the default order and its cursor stay within the readable fields", async () => {
  const rows = [
    { id: "00000000-0000-4000-8000-000000000001", name: "A" },
    { id: "00000000-0000-4000-8000-000000000002", name: "B" },
  ];
  const c = client(rows);
  const out = await data.list(c, ctx, collection, rule, { limit: 1 });
  assert.match(c.queries[0].text, /ORDER BY "id" ASC/);
  assert.doesNotMatch(c.queries[0].text, /salary|created_at/);
  const body = JSON.parse(Buffer.from(out.nextCursor.split(".")[0], "base64url").toString());
  assert.deepEqual(body.v, [rows[0].id, rows[0].id]);
  assert.deepEqual(out.items, [{ id: rows[0].id, name: "A" }]);
});

test("a readable field sorts and filters as before", async () => {
  const c = client([]);
  await data.list(c, ctx, collection, rule, { sort: "name", filters: [{ field: "name", op: "eq", value: "A" }] });
  assert.match(c.queries[0].text, /ORDER BY "name" ASC/);
});
