/**
 * Form fields for a document's `properties`, derived from its doc type's JSON
 * Schema (ADR-0015). Supports string (text or `format: "date"`), number,
 * integer and string arrays; anything else lands in `unsupported` and is left
 * untouched on save.
 */

type PropertyKind = "text" | "date" | "number" | "list";

export interface PropertyField {
  name: string;
  label: string;
  kind: PropertyKind;
  required: boolean;
  description?: string;
  /** `integer` schemas reject fractions. */
  integer?: boolean;
}

export interface PropertiesForm {
  fields: PropertyField[];
  /** Property names the form cannot edit. */
  unsupported: string[];
}

type Schema = Record<string, unknown>;

function isSchema(v: unknown): v is Schema {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function kindOf(schema: Schema): Pick<PropertyField, "kind" | "integer"> | null {
  switch (schema.type) {
    case "string":
      return { kind: schema.format === "date" ? "date" : "text" };
    case "number":
      return { kind: "number" };
    case "integer":
      return { kind: "number", integer: true };
    case "array": {
      const items = schema.items;
      return isSchema(items) && items.type === "string" ? { kind: "list" } : null;
    }
    default:
      return null;
  }
}

export function buildPropertiesForm(schema: unknown): PropertiesForm {
  const fields: PropertyField[] = [];
  const unsupported: string[] = [];
  if (!isSchema(schema) || !isSchema(schema.properties)) return { fields, unsupported };
  const required = Array.isArray(schema.required) ? schema.required : [];
  for (const [name, sub] of Object.entries(schema.properties)) {
    const kind = isSchema(sub) ? kindOf(sub) : null;
    if (!kind || !isSchema(sub)) {
      unsupported.push(name);
      continue;
    }
    fields.push({
      name,
      label: typeof sub.title === "string" && sub.title ? sub.title : name,
      required: required.includes(name),
      ...(typeof sub.description === "string" ? { description: sub.description } : {}),
      ...kind,
    });
  }
  return { fields, unsupported };
}

/** Stored value as the text an input shows. */
export function toInput(field: PropertyField, value: unknown): string {
  if (value === undefined || value === null) return "";
  if (field.kind === "list") return Array.isArray(value) ? value.join(", ") : "";
  return String(value);
}

export type ParsedInput = { ok: true; value: unknown } | { ok: false };

/** Input text as the stored value; `undefined` means "leave the property out". */
export function fromInput(field: PropertyField, text: string): ParsedInput {
  const trimmed = text.trim();
  if (!trimmed) return { ok: true, value: undefined };
  switch (field.kind) {
    case "text":
    case "date":
      return { ok: true, value: trimmed };
    case "number": {
      const n = Number(trimmed.replace(",", "."));
      if (!Number.isFinite(n) || (field.integer && !Number.isInteger(n))) return { ok: false };
      return { ok: true, value: n };
    }
    case "list":
      return {
        ok: true,
        value: trimmed
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
      };
  }
}

/**
 * `properties` to save: the form's fields over the stored object, so a value
 * the form cannot edit (an unsupported type) survives. Returns the names of
 * fields whose text does not parse instead.
 */
export function collectProperties(
  form: PropertiesForm,
  inputs: Readonly<Record<string, string>>,
  stored: Readonly<Record<string, unknown>>,
): { ok: true; value: Record<string, unknown> } | { ok: false; invalid: string[] } {
  const value: Record<string, unknown> = {};
  for (const name of form.unsupported) {
    if (name in stored) value[name] = stored[name];
  }
  const invalid: string[] = [];
  for (const field of form.fields) {
    const parsed = fromInput(field, inputs[field.name] ?? "");
    if (!parsed.ok) invalid.push(field.name);
    else if (parsed.value !== undefined) value[field.name] = parsed.value;
  }
  return invalid.length ? { ok: false, invalid } : { ok: true, value };
}
