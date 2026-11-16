// The restricted schema interpreter and the request-value checks of the broker.
import { test } from "node:test";
import assert from "node:assert/strict";
import { ValidationError, coerceQuery, validate } from "../src/broker/validate.js";
import { checkFieldValue, checkRows, checkValues } from "../src/broker/model.js";
import { mapPgError } from "../src/broker/db.js";

const body = {
  type: "object", additionalProperties: false, required: ["id", "n"],
  properties: { id: { type: "string", format: "uuid" }, n: { type: "integer", minimum: 1, maximum: 5 }, tags: { type: "array", maxItems: 2, items: { type: "string", maxLength: 3 } } },
};

test("valid input passes", () => {
  validate(body, { id: "3f2b6c1e-0f7e-4a51-9d38-6a2a7c9b1e00", n: 3, tags: ["a"] });
});

test("errors carry a JSON Pointer", () => {
  const cases = [
    [{ id: "x", n: 1 }, "/id"],
    [{ id: "3f2b6c1e-0f7e-4a51-9d38-6a2a7c9b1e00", n: 9 }, "/n"],
    [{ id: "3f2b6c1e-0f7e-4a51-9d38-6a2a7c9b1e00", n: 1, extra: 1 }, "/extra"],
    [{ id: "3f2b6c1e-0f7e-4a51-9d38-6a2a7c9b1e00", n: 1, tags: ["a", "b", "c"] }, "/tags"],
    [{ n: 1 }, "/id"],
  ];
  for (const [value, pointer] of cases) {
    assert.throws(() => validate(body, value), (e) => e instanceof ValidationError && e.pointer === pointer);
  }
});

test("deep nesting is bounded", () => {
  let schema = { type: "string", maxLength: 1 };
  let value = "a";
  for (let i = 0; i < 30; i += 1) {
    schema = { type: "array", maxItems: 1, items: schema };
    value = [value];
  }
  assert.throws(() => validate(schema, value), ValidationError);
});

test("query strings are coerced only for declared numeric and boolean fields", () => {
  const q = coerceQuery({ type: "object", properties: { limit: { type: "integer" }, flag: { type: "boolean" } } }, { limit: "5", flag: "true" });
  assert.deepEqual(q, { limit: 5, flag: true });
  assert.throws(() => coerceQuery({ type: "object", properties: {} }, { x: "1" }), ValidationError);
});

test("field values follow the data model", () => {
  assert.throws(() => checkFieldValue({ type: "decimal", precision: 5, scale: 2 }, "1234.5", "/p"), ValidationError);
  checkFieldValue({ type: "decimal", precision: 5, scale: 2 }, "123.45", "/p");
  assert.throws(() => checkFieldValue({ type: "date" }, "2026-02-30", "/d"), ValidationError);
  assert.throws(() => checkFieldValue({ type: "enum", values: ["a"] }, "b", "/e"), ValidationError);
  assert.throws(() => checkFieldValue({ type: "string", maxLength: 2, required: true }, null, "/s"), ValidationError);
});

test("driver errors map to stable codes, gateway errors pass through", () => {
  assert.equal(mapPgError({ code: "23514" }).status, 422);
  assert.equal(mapPgError({ code: "57014" }).code, "execution_deadline");
  assert.equal(mapPgError({ code: "XX000" }).status, 500);
  const http = Object.assign(new Error("x"), { status: 409, code: "idempotency_key_reused" });
  assert.equal(mapPgError(http), http);
});

test("seed rows get the same value rules as writes, with the system id and date", () => {
  const fields = { text: { type: "string", maxLength: 3 }, price: { type: "decimal", precision: 4, scale: 2 } };
  const problems = checkRows(fields, [
    { text: "ok", price: "12.50", id: "5b2d3c0e-8a1f-4c3e-9d2a-1f0e3c4b5a69", created_at: "2026-09-25T15:22:16Z" },
    { text: "toolong", price: 1.5, created_at: "2026-09-25T15:22:16" },
  ]);
  assert.deepEqual(problems.map((p) => p.pointer), ["/1/text", "/1/price", "/1/created_at"]);
  assert.equal(checkRows(fields, [{ text: "x" }, { text: "y" }, { text: "zzzz" }, { text: "wwww" }], 1).length, 1);
});

test("values a manifest states for fields get the write rules", () => {
  const problems = checkValues([
    { pointer: "/database/collections/a/fields/n/default", field: { type: "integer", maximum: 3 }, value: 9, code: "default_invalid" },
    { pointer: "/database/collections/a/fields/t/default", field: { type: "string", maxLength: 5, minLength: 2 }, value: "x" },
    { pointer: "/capabilities/c/conditions/s", field: { type: "enum", values: ["a"] }, value: "a" },
  ]);
  assert.deepEqual(problems.map((p) => p.pointer), ["/database/collections/a/fields/n/default", "/database/collections/a/fields/t/default"]);
  assert.equal(problems[0].code, "default_invalid");
});
