// Public description of the active release for its signed-in user: no schema
// names, roles or other physical bindings, only what the API offers.
import { SYSTEM_FIELDS } from "./model.js";

export function publicSchema(rc) {
  const { model, auth } = rc;
  const collections = {};
  for (const [name, c] of model.collections) {
    const ops = {};
    for (const [op, rule] of Object.entries(c.crud)) {
      ops[op] = { allowed: rc.permissions.has(rule.permission), rowScope: rule.rowScope, writeFields: rule.writeFields, conditions: rule.conditions };
    }
    collections[name] = { fields: c.fields, systemFields: SYSTEM_FIELDS, operations: ops };
  }
  const endpoints = model.endpoints.map((e) => ({ name: e.name, method: e.method, path: `/api${e.path}`, allowed: rc.permissions.has(e.permission), ifMatch: e.ifMatch, idempotency: e.idempotency, input: e.input, output: e.output }));
  return { contractVersion: model.manifest.apiVersion, release: auth.release.id, digest: auth.release.digest, title: model.manifest.metadata.title, collections, endpoints };
}

const FIELD_SCHEMA = {
  string: (f) => ({ type: "string", maxLength: f.maxLength }),
  integer: (f) => ({ type: "integer", minimum: f.minimum, maximum: f.maximum }),
  boolean: () => ({ type: "boolean" }),
  decimal: () => ({ type: "string", pattern: "^-?\\d+(\\.\\d+)?$" }),
  date: () => ({ type: "string", format: "date" }),
  timestamptz: () => ({ type: "string", format: "date-time" }),
  uuid: () => ({ type: "string", format: "uuid" }),
  enum: (f) => ({ type: "string", enum: f.values }),
  json: () => ({}),
};

export function buildOpenApi(rc) {
  const { model, auth } = rc;
  const paths = {};
  const schemas = {};
  for (const [name, c] of model.collections) {
    const props = { id: { type: "string", format: "uuid" }, created_by: { type: "string", format: "uuid" }, created_at: { type: "string", format: "date-time" }, updated_at: { type: "string", format: "date-time" }, revision: { type: "integer" } };
    for (const [f, def] of Object.entries(c.fields)) props[f] = FIELD_SCHEMA[def.type](def);
    schemas[name] = { type: "object", properties: props };
    const ref = { $ref: `#/components/schemas/${name}` };
    const base = `/api/v1/collections/${name}`;
    paths[base] = {};
    if (c.crud.list) paths[base].get = { summary: `List ${name}`, responses: { 200: { description: "page", content: { "application/json": { schema: { type: "object", properties: { items: { type: "array", items: ref }, nextCursor: { type: "string" } } } } } } } };
    if (c.crud.create) paths[base].post = { summary: `Create ${name}`, parameters: [{ name: "Idempotency-Key", in: "header", required: true, schema: { type: "string" } }], responses: { 201: { description: "created" } } };
    const item = `${base}/{id}`;
    paths[item] = {};
    if (c.crud.get) paths[item].get = { summary: `Get ${name}`, responses: { 200: { description: "record", content: { "application/json": { schema: ref } } } } };
    if (c.crud.update) paths[item].patch = { summary: `Update ${name}`, parameters: [{ name: "If-Match", in: "header", required: true, schema: { type: "string" } }], responses: { 200: { description: "updated" } } };
    if (c.crud.delete) paths[item].delete = { summary: `Delete ${name}`, parameters: [{ name: "If-Match", in: "header", required: true, schema: { type: "string" } }, { name: "Idempotency-Key", in: "header", required: true, schema: { type: "string" } }], responses: { 204: { description: "deleted" } } };
  }
  for (const e of model.endpoints) {
    const p = `/api${e.path.replace(/:([a-z][a-z0-9_]*)/g, "{$1}")}`;
    paths[p] ??= {};
    paths[p][e.method.toLowerCase()] = {
      operationId: e.name,
      requestBody: e.input.body ? { content: { "application/json": { schema: e.input.body } } } : undefined,
      responses: { 200: { description: "result", content: { "application/json": { schema: e.output } } } },
    };
  }
  return { openapi: "3.1.0", info: { title: model.manifest.metadata.title, version: auth.release.id, "x-ics-release-digest": auth.release.digest }, paths, components: { schemas } };
}
