// Controlled data operations: the only SQL the broker runs on behalf of an
// application. Generic CRUD and handler capabilities both end up here, so the
// same rules (permission, row scope, conditions, field lists, revision) apply
// whichever way a request arrives. Identifiers come from the release model,
// values are always bound parameters.
import crypto from "node:crypto";
import { SYSTEM_FIELDS, quoteIdent, isUuid } from "./model.js";
import { ValidationError, escapePointer } from "./validate.js";

export class DataError extends Error {
  constructor(status, code, message, extra = {}) {
    super(message ?? code);
    this.status = status;
    this.code = code;
    Object.assign(this, extra);
  }
}

const MAX_LIMIT = 200;
const DEFAULT_LIMIT = 50;
const MAX_FILTERS = 8;
const FILTER_OPS = new Set(["eq", "in", "lt", "lte", "gt", "gte"]);
const OP_SQL = { eq: "=", lt: "<", lte: "<=", gt: ">", gte: ">=" };

/** Rule shared by CRUD and capabilities. */
export function crudRule(collection, op) {
  const rule = collection.crud[op];
  if (!rule) return null;
  const operation = { create: "insert", list: "list", get: "get", update: "update", delete: "delete" }[op];
  return { ...rule, collection: collection.name, operation, key: `crud:${collection.name}:${op}` };
}

export function capabilityRule(model, name, operation) {
  const cap = model.capabilities[name];
  if (!cap) throw new DataError(403, "capability_unknown", "unknown capability");
  if (cap.operation !== operation) throw new DataError(403, "capability_operation_mismatch", "capability does not allow this operation");
  return { ...cap, key: `cap:${name}` };
}

export function assertPermission(rule, permissions) {
  if (!permissions.has(rule.permission)) {
    throw new DataError(403, "forbidden", "operation not permitted");
  }
}

class Sql {
  constructor() {
    this.params = [];
  }
  bind(value) {
    this.params.push(value);
    return `$${this.params.length}`;
  }
}

function scopeClauses(sql, rule, actorId, collection) {
  const clauses = [];
  if (rule.rowScope === "own") clauses.push(`created_by = ${sql.bind(actorId)}`);
  else if (rule.rowScope === "not_own") clauses.push(`created_by <> ${sql.bind(actorId)}`);
  else if (rule.rowScope !== "all") throw new DataError(403, "forbidden", "no row scope");
  for (const [field, value] of Object.entries(rule.conditions ?? {})) {
    clauses.push(value === null ? `${quoteIdent(field)} IS NULL` : `${quoteIdent(field)} = ${sql.bind(collection.toParam(field, value))}`);
  }
  return clauses;
}

function projection(fields) {
  return fields.map(quoteIdent).join(", ");
}

function readFieldsOf(rule, collection) {
  return rule.readFields ?? collection.allFields();
}

function filterClauses(sql, collection, filters, allowed) {
  if (!Array.isArray(filters)) throw new ValidationError("/filters", "must be an array");
  if (filters.length > MAX_FILTERS) throw new ValidationError("/filters", `at most ${MAX_FILTERS} filters`);
  return filters.map((f, i) => {
    const pointer = `/filters/${i}`;
    if (!f || typeof f !== "object") throw new ValidationError(pointer, "must be an object");
    const type = collection.fieldType(f.field);
    if (!type || type.type === "json" || !allowed.has(f.field)) throw new ValidationError(`${pointer}/field`, "field cannot be filtered");
    if (!FILTER_OPS.has(f.op)) throw new ValidationError(`${pointer}/op`, "unsupported operator");
    if (f.op === "in") {
      if (!Array.isArray(f.value) || f.value.length === 0 || f.value.length > 50) throw new ValidationError(`${pointer}/value`, "must be a non-empty array");
      return `${quoteIdent(f.field)} = ANY(${sql.bind(f.value)})`;
    }
    if (f.value === null || typeof f.value === "object") throw new ValidationError(`${pointer}/value`, "must be a scalar");
    return `${quoteIdent(f.field)} ${OP_SQL[f.op]} ${sql.bind(f.value)}`;
  });
}

// Signed keyset cursor bound to the app, environment, rule, filters and sort.
function cursorKey(ctx, rule, filters, sort) {
  return crypto
    .createHash("sha256")
    .update(JSON.stringify([ctx.assetId, ctx.environment, ctx.dataGeneration, rule.key, filters, sort, ctx.actorId]))
    .digest("base64url");
}

function encodeCursor(ctx, binding, last) {
  const body = Buffer.from(JSON.stringify({ b: binding, v: last })).toString("base64url");
  const sig = crypto.createHmac("sha256", ctx.cursorSecret).update(body).digest("base64url");
  return `${body}.${sig}`;
}

function decodeCursor(ctx, binding, cursor) {
  if (typeof cursor !== "string" || cursor.length > 2048) throw new ValidationError("/cursor", "invalid cursor");
  const [body, sig] = cursor.split(".");
  const expected = crypto.createHmac("sha256", ctx.cursorSecret).update(body ?? "").digest("base64url");
  if (!sig || sig.length !== expected.length || !crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(expected))) {
    throw new ValidationError("/cursor", "invalid cursor");
  }
  const parsed = JSON.parse(Buffer.from(body, "base64url").toString());
  if (parsed.b !== binding) throw new ValidationError("/cursor", "cursor does not match this query");
  return parsed.v;
}

function parseSort(sort, collection) {
  const raw = sort ?? "-created_at";
  const desc = raw.startsWith("-");
  const field = desc ? raw.slice(1) : raw;
  const type = collection.fieldType(field);
  if (!type || type.type === "json") throw new ValidationError("/sort", "field cannot be sorted");
  return { field, desc };
}

export async function get(client, ctx, collection, rule, id) {
  if (!isUuid(id)) return null;
  const sql = new Sql();
  const where = [`id = ${sql.bind(id)}`, ...scopeClauses(sql, rule, ctx.actorId, collection)];
  const lock = rule.lock ? " FOR UPDATE" : "";
  const res = await client.query(`SELECT ${projection(readFieldsOf(rule, collection))} FROM ${collection.table} WHERE ${where.join(" AND ")}${lock}`, sql.params);
  return res.rows[0] ?? null;
}

export async function list(client, ctx, collection, rule, query) {
  const limit = query.limit ?? DEFAULT_LIMIT;
  if (!Number.isInteger(limit) || limit < 1 || limit > MAX_LIMIT) throw new ValidationError("/limit", `must be 1..${MAX_LIMIT}`);
  const readFields = readFieldsOf(rule, collection);
  const filters = query.filters ?? [];
  const sort = parseSort(query.sort, collection);
  const sql = new Sql();
  const where = [...scopeClauses(sql, rule, ctx.actorId, collection), ...filterClauses(sql, collection, filters, new Set(collection.allFields()))];
  const binding = cursorKey(ctx, rule, filters, query.sort ?? null);
  if (query.cursor) {
    const [value, id] = decodeCursor(ctx, binding, query.cursor);
    const cmp = sort.desc ? "<" : ">";
    where.push(`(${quoteIdent(sort.field)}, id) ${cmp} (${sql.bind(value)}, ${sql.bind(id)})`);
  }
  const dir = sort.desc ? "DESC" : "ASC";
  const select = [...new Set([...readFields, sort.field, "id"])];
  const text = `SELECT ${projection(select)} FROM ${collection.table}${where.length ? ` WHERE ${where.join(" AND ")}` : ""} ORDER BY ${quoteIdent(sort.field)} ${dir}, id ${dir} LIMIT ${limit + 1}`;
  const res = await client.query(text, sql.params);
  const rows = res.rows.slice(0, limit);
  const out = { items: rows.map((r) => pick(r, readFields)) };
  if (res.rows.length > limit) {
    const last = rows[rows.length - 1];
    out.nextCursor = encodeCursor(ctx, binding, [last[sort.field], last.id]);
  }
  return out;
}

function pick(row, fields) {
  const out = {};
  for (const f of fields) if (row[f] !== undefined) out[f] = row[f];
  return out;
}

async function audit(client, ctx, action, collection, recordId, details = {}) {
  await client.query(
    `INSERT INTO ${quoteIdent(ctx.schema)}."_ics_audit" (actor, action, collection, record_id, request_id, release_id, details) VALUES ($1, $2, $3, $4, $5, $6, $7)`,
    [ctx.actorId, action, collection.name, recordId, ctx.requestId, ctx.releaseId, JSON.stringify(details)],
  );
}

function assertRoom(ctx) {
  if (ctx.dataFull) throw new DataError(507, "app_data_quota_exceeded", "the owner's micro-application data quota is full; delete records to make room");
}

export async function insert(client, ctx, collection, rule, data, { returnFields } = {}) {
  assertRoom(ctx);
  collection.checkWrite(data, rule.writeFields, { partial: false, allowedValues: rule.allowedValues });
  for (const [field, value] of Object.entries(rule.conditions ?? {})) {
    // An insert under a condition must create a row that satisfies it.
    if (Object.hasOwn(data, field) && data[field] !== value) throw new ValidationError(`/${escapePointer(field)}`, "value is not allowed for this operation");
  }
  const id = crypto.randomUUID();
  const sql = new Sql();
  const cols = ["id", "created_by"];
  const vals = [sql.bind(id), sql.bind(ctx.actorId)];
  for (const [field, value] of Object.entries(data)) {
    cols.push(quoteIdent(field));
    vals.push(sql.bind(collection.toParam(field, value)));
  }
  const ret = returnFields ?? rule.returnFields ?? ["id", "revision"];
  const res = await client.query(`INSERT INTO ${collection.table} (${cols.join(", ")}) VALUES (${vals.join(", ")}) RETURNING ${projection(ret)}`, sql.params);
  await audit(client, ctx, "insert", collection, id, { fields: Object.keys(data) });
  return res.rows[0];
}

async function explainMiss(client, ctx, collection, rule, id, expectedRevision) {
  // Why did a conditional write touch no row? Only rows visible under the
  // rule's row scope get a specific answer; everything else is a plain 404.
  const sql = new Sql();
  const where = [`id = ${sql.bind(id)}`];
  if (rule.rowScope === "own") where.push(`created_by = ${sql.bind(ctx.actorId)}`);
  if (rule.rowScope === "not_own") where.push(`created_by <> ${sql.bind(ctx.actorId)}`);
  const res = await client.query(`SELECT revision FROM ${collection.table} WHERE ${where.join(" AND ")}`, sql.params);
  if (!res.rows[0]) return new DataError(404, "not_found", "record not found");
  if (expectedRevision !== undefined && res.rows[0].revision !== expectedRevision) {
    return new DataError(412, "revision_mismatch", "the record changed", { currentRevision: res.rows[0].revision });
  }
  return new DataError(409, "invalid_state", "the record does not meet the operation's conditions");
}

function requireRevision(ifRevision) {
  if (!Number.isSafeInteger(ifRevision) || ifRevision < 1) throw new DataError(428, "precondition_required", "a record revision (If-Match) is required");
}

export async function update(client, ctx, collection, rule, id, patch, ifRevision, { returnFields } = {}) {
  assertRoom(ctx);
  requireRevision(ifRevision);
  if (!isUuid(id)) throw new DataError(404, "not_found", "record not found");
  collection.checkWrite(patch, rule.writeFields, { partial: true, allowedValues: rule.allowedValues });
  if (Object.keys(patch).length === 0) throw new ValidationError("", "nothing to update");
  const sql = new Sql();
  const sets = Object.entries(patch).map(([f, v]) => `${quoteIdent(f)} = ${sql.bind(collection.toParam(f, v))}`);
  sets.push("revision = revision + 1", "updated_at = now()");
  const where = [`id = ${sql.bind(id)}`, `revision = ${sql.bind(ifRevision)}`, ...scopeClauses(sql, rule, ctx.actorId, collection)];
  const ret = returnFields ?? rule.returnFields ?? ["id", "revision"];
  const res = await client.query(`UPDATE ${collection.table} SET ${sets.join(", ")} WHERE ${where.join(" AND ")} RETURNING ${projection(ret)}`, sql.params);
  if (!res.rows[0]) throw await explainMiss(client, ctx, collection, rule, id, ifRevision);
  await audit(client, ctx, "update", collection, id, { fields: Object.keys(patch), fromRevision: ifRevision });
  return res.rows[0];
}

export async function remove(client, ctx, collection, rule, id, ifRevision) {
  requireRevision(ifRevision);
  if (!isUuid(id)) throw new DataError(404, "not_found", "record not found");
  const sql = new Sql();
  const where = [`id = ${sql.bind(id)}`, `revision = ${sql.bind(ifRevision)}`, ...scopeClauses(sql, rule, ctx.actorId, collection)];
  const res = await client.query(`DELETE FROM ${collection.table} WHERE ${where.join(" AND ")} RETURNING id`, sql.params);
  if (!res.rows[0]) throw await explainMiss(client, ctx, collection, rule, id, ifRevision);
  await audit(client, ctx, "delete", collection, id, { revision: ifRevision });
}

export async function count(client, ctx, collection, rule, filters) {
  const sql = new Sql();
  const where = [...scopeClauses(sql, rule, ctx.actorId, collection), ...filterClauses(sql, collection, filters, new Set(readFieldsOf(rule, collection)))];
  const res = await client.query(`SELECT count(*)::int AS n FROM ${collection.table}${where.length ? ` WHERE ${where.join(" AND ")}` : ""}`, sql.params);
  return res.rows[0].n;
}

export async function groupCount(client, ctx, collection, rule, field, filters) {
  const groupable = new Set(readFieldsOf(rule, collection));
  const type = collection.fieldType(field);
  if (!type || type.type === "json" || !groupable.has(field)) throw new ValidationError("/field", "field cannot be grouped");
  const sql = new Sql();
  const where = [...scopeClauses(sql, rule, ctx.actorId, collection), ...filterClauses(sql, collection, filters, groupable)];
  const res = await client.query(
    `SELECT ${quoteIdent(field)} AS value, count(*)::int AS count FROM ${collection.table}${where.length ? ` WHERE ${where.join(" AND ")}` : ""} GROUP BY 1 ORDER BY 2 DESC LIMIT 200`,
    sql.params,
  );
  return res.rows;
}

export { SYSTEM_FIELDS };
