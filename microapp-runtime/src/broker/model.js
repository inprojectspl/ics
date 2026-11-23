// Data model of an active release, derived from its validated manifest.
// The ICS publication pipeline already validated the manifest; these checks
// are about request values, not about the manifest itself.
import { ValidationError, escapePointer, isValidDate } from "./validate.js";

export const SYSTEM_FIELDS = ["id", "created_by", "created_at", "updated_at", "revision"];
const SYSTEM_TYPES = {
  id: { type: "uuid" },
  created_by: { type: "uuid" },
  created_at: { type: "timestamptz" },
  updated_at: { type: "timestamptz" },
  revision: { type: "integer" },
};
export const IDENT_RE = /^[a-z][a-z0-9_]{0,47}$/;
// An app channel's message size when the manifest names none (ADR-0032).
const RT_APP_MESSAGE_BYTES = 65536;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function quoteIdent(name) {
  if (!/^[a-z_][a-z0-9_]{0,62}$/.test(name)) throw new Error(`unsafe identifier: ${name}`);
  return `"${name}"`;
}

export class Model {
  constructor(manifest, schemaName) {
    this.manifest = manifest;
    this.schema = schemaName;
    this.collections = new Map();
    for (const [name, def] of Object.entries(manifest.database.collections)) {
      if (!IDENT_RE.test(name)) throw new Error(`bad collection name ${name}`);
      this.collections.set(name, new Collection(name, def, schemaName));
    }
    this.capabilities = manifest.capabilities ?? {};
    this.endpoints = (manifest.endpoints ?? []).map((e) => ({ ...e, matcher: compilePath(e.path) }));
    this.channels = parseChannels(manifest);
  }

  collection(name) {
    const c = this.collections.get(name);
    if (!c) throw Object.assign(new Error("unknown collection"), { status: 404, code: "not_found" });
    return c;
  }

  matchEndpoint(method, path) {
    for (const endpoint of this.endpoints) {
      if (endpoint.method !== method) continue;
      const params = endpoint.matcher(path);
      if (params) return { endpoint, params };
    }
    return null;
  }
}

/**
 * `realtime.channels` of the manifest: name -> {name, permission, presence,
 * maxMessageBytes, messagesPerSecond}. ICS validated the manifest at
 * publication; only the name is checked again, because it becomes part of
 * Redis keys. The broker's frame cap (ws maxPayload) bounds any size.
 */
export function parseChannels(manifest) {
  const channels = new Map();
  for (const [name, def] of Object.entries(manifest.realtime?.channels ?? {})) {
    if (!IDENT_RE.test(name)) throw new Error(`realtime channel ${name}: name must match ^[a-z][a-z0-9_]{0,47}$`);
    channels.set(name, {
      name,
      permission: def.permission,
      presence: def.presence === true,
      maxMessageBytes: def.maxMessageBytes ?? RT_APP_MESSAGE_BYTES,
      messagesPerSecond: def.messagesPerSecond ?? null,
    });
  }
  return channels;
}

function compilePath(template) {
  const parts = template.split("/").filter(Boolean);
  return (path) => {
    const segs = path.split("/").filter(Boolean);
    if (segs.length !== parts.length) return null;
    const params = {};
    for (let i = 0; i < parts.length; i += 1) {
      const p = parts[i];
      let seg;
      try {
        seg = decodeURIComponent(segs[i]);
      } catch {
        return null;
      }
      if (p.startsWith(":")) params[p.slice(1)] = seg;
      else if (p !== seg) return null;
    }
    return params;
  };
}

export class Collection {
  constructor(name, def, schemaName) {
    this.name = name;
    this.def = def;
    this.fields = def.fields;
    this.crud = def.crud ?? {};
    this.table = `${quoteIdent(schemaName)}.${quoteIdent(name)}`;
  }

  fieldType(name) {
    return this.fields[name] ?? SYSTEM_TYPES[name] ?? null;
  }

  allFields() {
    return [...SYSTEM_FIELDS, ...Object.keys(this.fields)];
  }

  /** Validate a write payload against the allowed field list. */
  checkWrite(data, writeFields, { partial, allowedValues = {} } = {}) {
    if (data === null || typeof data !== "object" || Array.isArray(data)) throw new ValidationError("", "must be an object");
    const allowed = new Set(writeFields ?? []);
    for (const key of Object.keys(data)) {
      if (!allowed.has(key)) {
        const why = SYSTEM_FIELDS.includes(key) || Object.hasOwn(this.fields, key) ? "field is not writable here" : "unknown field";
        throw new ValidationError(`/${escapePointer(key)}`, why);
      }
    }
    if (!partial) {
      for (const [name, f] of Object.entries(this.fields)) {
        if (f.required && f.default === undefined && !Object.hasOwn(data, name)) {
          throw new ValidationError(`/${escapePointer(name)}`, "is required");
        }
      }
    }
    for (const [key, value] of Object.entries(data)) {
      checkFieldValue(this.fields[key], value, `/${escapePointer(key)}`);
      if (allowedValues[key] && !allowedValues[key].some((v) => v === value)) {
        throw new ValidationError(`/${escapePointer(key)}`, "value is not allowed for this operation");
      }
    }
  }

  /** Convert a JSON value to the SQL parameter for `field`. */
  toParam(field, value) {
    const f = this.fieldType(field);
    if (value === null) return null;
    if (f.type === "json") return JSON.stringify(value);
    return value;
  }
}

export function checkFieldValue(f, value, pointer) {
  if (value === null) {
    if (f.required) throw new ValidationError(pointer, "cannot be null");
    return;
  }
  switch (f.type) {
    case "string":
      if (typeof value !== "string") throw new ValidationError(pointer, "must be a string");
      if ([...value].length > f.maxLength) throw new ValidationError(pointer, `at most ${f.maxLength} characters`);
      if (f.minLength !== undefined && [...value].length < f.minLength) throw new ValidationError(pointer, `at least ${f.minLength} characters`);
      return;
    case "integer":
      if (!Number.isSafeInteger(value)) throw new ValidationError(pointer, "must be an integer");
      if (f.minimum !== undefined && value < f.minimum) throw new ValidationError(pointer, `must be >= ${f.minimum}`);
      if (f.maximum !== undefined && value > f.maximum) throw new ValidationError(pointer, `must be <= ${f.maximum}`);
      return;
    case "boolean":
      if (typeof value !== "boolean") throw new ValidationError(pointer, "must be a boolean");
      return;
    case "decimal": {
      if (typeof value !== "string" || !/^-?\d+(\.\d+)?$/.test(value)) throw new ValidationError(pointer, "must be a decimal string");
      const [intPart, frac = ""] = value.replace("-", "").split(".");
      if (frac.length > f.scale || intPart.replace(/^0+(?=\d)/, "").length > f.precision - f.scale) {
        throw new ValidationError(pointer, `exceeds precision ${f.precision} / scale ${f.scale}`);
      }
      return;
    }
    case "date":
      if (typeof value !== "string" || !isValidDate(value)) throw new ValidationError(pointer, "must be a date (YYYY-MM-DD)");
      return;
    case "timestamptz":
      if (typeof value !== "string" || Number.isNaN(Date.parse(value)) || !/Z|[+-]\d{2}:\d{2}$/.test(value)) {
        throw new ValidationError(pointer, "must be an ISO 8601 timestamp with zone");
      }
      return;
    case "uuid":
      if (typeof value !== "string" || !UUID_RE.test(value)) throw new ValidationError(pointer, "must be a UUID");
      return;
    case "enum":
      if (!f.values.includes(value)) throw new ValidationError(pointer, "value is not allowed");
      return;
    case "json": {
      const size = Buffer.byteLength(JSON.stringify(value));
      if (size > (f.maxBytes ?? 65536)) throw new ValidationError(pointer, "JSON value too large");
      return;
    }
    default:
      throw new ValidationError(pointer, "unsupported field type");
  }
}

const SEED_SYSTEM = { id: { type: "uuid" }, created_at: { type: "timestamptz" } };

/** Problems of values meant for fields, each `{ pointer, field, value }`
 * with optional `code` (echoed) and `label` (prefixes the message): the
 * rules of a write through the app's API. */
export function checkValues(items, max = 100) {
  const problems = [];
  for (const { pointer, field, value, code, label } of items) {
    try {
      checkFieldValue(field, value, pointer);
    } catch (e) {
      if (!(e instanceof ValidationError)) throw e;
      problems.push({ pointer, code, message: label ? `${label}: ${e.message}` : e.message });
      if (problems.length >= max) break;
    }
  }
  return problems;
}

/** Value problems of seed rows (structure is checked by ICS), with the
 * system id and date a seed may carry. */
export function checkRows(fields, rows, max = 100) {
  const items = rows.flatMap((row, i) =>
    Object.entries(row)
      .filter(([key]) => SEED_SYSTEM[key] ?? fields[key])
      .map(([key, value]) => ({ pointer: `/${i}/${escapePointer(key)}`, field: SEED_SYSTEM[key] ?? fields[key], value, label: key })),
  );
  return checkValues(items, max);
}

export function isUuid(value) {
  return typeof value === "string" && UUID_RE.test(value);
}
