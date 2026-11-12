// Interpreter of the restricted schema language from the manifest
// (closed objects, bounded arrays, primitive values, uuid/date/date-time).
// No code generation: author schemas are data walked by this function, never
// compiled into validators: generated validator code from untrusted schemas
// is a code-injection risk (Fastify's documentation warns about the same).
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const DATETIME_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$/;
const MAX_DEPTH = 16;
const MAX_NODES = 20000;

export class ValidationError extends Error {
  constructor(pointer, message) {
    super(message);
    this.pointer = pointer;
    this.code = "validation_failed";
  }
}

export function isValidDate(value) {
  if (!DATE_RE.test(value)) return false;
  const d = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === value;
}

function checkFormat(format, value, pointer) {
  if (format === "uuid" && !UUID_RE.test(value)) throw new ValidationError(pointer, "must be a UUID");
  if (format === "date" && !isValidDate(value)) throw new ValidationError(pointer, "must be a date (YYYY-MM-DD)");
  if (format === "date-time" && (!DATETIME_RE.test(value) || Number.isNaN(Date.parse(value)))) {
    throw new ValidationError(pointer, "must be an ISO 8601 date-time");
  }
}

/**
 * Validate `value` against a restricted schema. Throws ValidationError with a
 * JSON Pointer of the first offending location.
 */
export function validate(schema, value, pointer = "", state = { nodes: 0 }, depth = 0) {
  state.nodes += 1;
  if (state.nodes > MAX_NODES || depth > MAX_DEPTH) throw new ValidationError(pointer, "value too deeply nested or too large");
  const type = schema.type;
  if (schema.enum && !schema.enum.some((v) => v === value)) {
    throw new ValidationError(pointer, "value is not allowed");
  }
  switch (type) {
    case "object": {
      if (value === null || typeof value !== "object" || Array.isArray(value)) throw new ValidationError(pointer, "must be an object");
      const props = schema.properties ?? {};
      for (const key of Object.keys(value)) {
        if (!Object.hasOwn(props, key)) throw new ValidationError(`${pointer}/${escapePointer(key)}`, "unknown property");
      }
      for (const key of schema.required ?? []) {
        if (!Object.hasOwn(value, key)) throw new ValidationError(`${pointer}/${escapePointer(key)}`, "is required");
      }
      for (const [key, sub] of Object.entries(props)) {
        if (Object.hasOwn(value, key)) validate(sub, value[key], `${pointer}/${escapePointer(key)}`, state, depth + 1);
      }
      return;
    }
    case "array": {
      if (!Array.isArray(value)) throw new ValidationError(pointer, "must be an array");
      if (value.length > schema.maxItems) throw new ValidationError(pointer, `at most ${schema.maxItems} items`);
      if (schema.minItems !== undefined && value.length < schema.minItems) throw new ValidationError(pointer, `at least ${schema.minItems} items`);
      value.forEach((item, i) => validate(schema.items, item, `${pointer}/${i}`, state, depth + 1));
      return;
    }
    case "string":
      if (typeof value !== "string") throw new ValidationError(pointer, "must be a string");
      if (schema.maxLength !== undefined && [...value].length > schema.maxLength) throw new ValidationError(pointer, `at most ${schema.maxLength} characters`);
      if (schema.minLength !== undefined && [...value].length < schema.minLength) throw new ValidationError(pointer, `at least ${schema.minLength} characters`);
      if (schema.format) checkFormat(schema.format, value, pointer);
      return;
    case "integer":
      if (!Number.isSafeInteger(value)) throw new ValidationError(pointer, "must be an integer");
      rangeCheck(schema, value, pointer);
      return;
    case "number":
      if (typeof value !== "number" || !Number.isFinite(value)) throw new ValidationError(pointer, "must be a number");
      rangeCheck(schema, value, pointer);
      return;
    case "boolean":
      if (typeof value !== "boolean") throw new ValidationError(pointer, "must be a boolean");
      return;
    case "null":
      if (value !== null) throw new ValidationError(pointer, "must be null");
      return;
    default:
      throw new ValidationError(pointer, "unsupported schema");
  }
}

function rangeCheck(schema, value, pointer) {
  if (schema.minimum !== undefined && value < schema.minimum) throw new ValidationError(pointer, `must be >= ${schema.minimum}`);
  if (schema.maximum !== undefined && value > schema.maximum) throw new ValidationError(pointer, `must be <= ${schema.maximum}`);
}

export function escapePointer(key) {
  return String(key).replaceAll("~", "~0").replaceAll("/", "~1");
}

/**
 * Coerce query-string values (always strings) for a restricted object schema,
 * then validate. Only integer/number/boolean properties are converted.
 */
export function coerceQuery(schema, query) {
  const out = {};
  const props = schema?.properties ?? {};
  for (const [key, raw] of Object.entries(query)) {
    const sub = props[key];
    if (!sub) throw new ValidationError(`/${escapePointer(key)}`, "unknown query parameter");
    if (sub.type === "integer" || sub.type === "number") {
      const n = Number(raw);
      out[key] = raw.trim() === "" ? raw : n;
    } else if (sub.type === "boolean") {
      out[key] = raw === "true" ? true : raw === "false" ? false : raw;
    } else {
      out[key] = raw;
    }
  }
  return out;
}
