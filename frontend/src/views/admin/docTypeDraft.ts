import type { AdminDocType, DocTypeCreate, DocTypeUpdate } from "../../api";

/** Form state: every field as typed, converted only on save. */
export interface DocTypeDraft {
  key: string;
  label_pl: string;
  label_en: string;
  agent_hint: string;
  default_review_days: string;
  position: string;
  properties_schema: string;
}

export type SchemaParse =
  | { ok: true; value: Record<string, unknown> }
  | { ok: false; reason: "syntax" | "not_object" };

/** Doc type keys are snake case (ADR-0015); the backend enforces the same. */
export const DOC_TYPE_KEY = /^[a-z][a-z0-9_]{0,31}$/;

export function emptyDraft(): DocTypeDraft {
  return {
    key: "",
    label_pl: "",
    label_en: "",
    agent_hint: "",
    default_review_days: "",
    position: "",
    properties_schema: "{}",
  };
}

export function draftOf(d: AdminDocType): DocTypeDraft {
  return {
    key: d.key,
    label_pl: d.label_pl,
    label_en: d.label_en,
    agent_hint: d.agent_hint ?? "",
    default_review_days: d.default_review_days == null ? "" : String(d.default_review_days),
    position: String(d.position),
    properties_schema: JSON.stringify(d.properties_schema, null, 2),
  };
}

/** A JSON Schema must be an object; an empty editor means no properties. */
export function parseSchema(text: string): SchemaParse {
  if (!text.trim()) return { ok: true, value: {} };
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    return { ok: false, reason: "syntax" };
  }
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return { ok: false, reason: "not_object" };
  }
  return { ok: true, value: value as Record<string, unknown> };
}

/** Non-negative whole number, or null for an empty field; NaN when invalid. */
export function parseCount(text: string): number | null {
  const trimmed = text.trim();
  if (!trimmed) return null;
  return /^\d+$/.test(trimmed) ? Number(trimmed) : Number.NaN;
}

function common(d: DocTypeDraft, schema: Record<string, unknown>): Omit<DocTypeCreate, "key"> {
  const position = parseCount(d.position);
  return {
    label_pl: d.label_pl.trim(),
    label_en: d.label_en.trim(),
    agent_hint: d.agent_hint.trim() || null,
    default_review_days: parseCount(d.default_review_days),
    properties_schema: schema,
    ...(position === null ? {} : { position }),
  };
}

export function createPayload(d: DocTypeDraft, schema: Record<string, unknown>): DocTypeCreate {
  return { key: d.key.trim(), ...common(d, schema) };
}

export function updatePayload(d: DocTypeDraft, schema: Record<string, unknown>): DocTypeUpdate {
  return common(d, schema);
}
