import type { AssetMetaPatch, AssetMetaView } from "../../api";
import { collectProperties, type PropertiesForm } from "./propertiesForm";

/** Every editable field as its input text. */
export interface MetaDraft {
  summary: string;
  doc_type: string;
  maintainer_id: string;
  review_date: string;
  language: string;
  tags: string;
  /** Property inputs by property name. */
  properties: Record<string, string>;
}

/** Draft from the stored metadata; property inputs follow the doc type's form. */
export function initialDraft(meta: AssetMetaView): MetaDraft {
  return {
    summary: meta.summary ?? "",
    doc_type: meta.doc_type ?? "",
    maintainer_id: meta.maintainer?.id ?? "",
    review_date: dateInput(meta.review_due_at),
    language: meta.language ?? "",
    tags: meta.tags.join(", "),
    properties: {},
  };
}

function parseTags(text: string): string[] {
  const seen = new Set<string>();
  for (const raw of text.split(",")) {
    const tag = raw.trim().toLowerCase();
    if (tag) seen.add(tag);
  }
  return [...seen];
}

const orNull = (s: string) => s.trim() || null;

/** JSON with object keys sorted, so key order never counts as a change. */
function stable(value: unknown): string {
  return JSON.stringify(value, (_key, v: unknown) =>
    v && typeof v === "object" && !Array.isArray(v)
      ? Object.fromEntries(Object.entries(v).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)))
      : v,
  );
}

/** `YYYY-MM-DD` for a date input from an ISO timestamp. */
const dateInput = (iso: string | null | undefined) => (iso ? iso.slice(0, 10) : "");

export interface MetaChanges {
  patch: AssetMetaPatch;
  /** New tag list, only when it differs. */
  tags?: string[];
}

/**
 * What to send: only the fields that differ from `meta`. Properties are
 * compared as a whole, since the backend replaces the object.
 */
export function buildChanges(
  draft: MetaDraft,
  meta: AssetMetaView,
  /** Form of the chosen doc type; `null` while its schema is unknown, which
   * leaves `properties` alone rather than wiping them. */
  form: PropertiesForm | null,
): { ok: true; changes: MetaChanges } | { ok: false; invalid: string[] } {
  const patch: AssetMetaPatch = {};
  const summary = orNull(draft.summary);
  if (summary !== meta.summary) patch.summary = summary;
  const docType = orNull(draft.doc_type);
  if (docType !== meta.doc_type) patch.doc_type = docType;
  const maintainer = orNull(draft.maintainer_id);
  if (maintainer !== (meta.maintainer?.id ?? null)) patch.maintainer_id = maintainer;
  if (draft.review_date !== dateInput(meta.review_due_at)) {
    patch.review_due_at = draft.review_date ? `${draft.review_date}T00:00:00Z` : null;
  }
  const language = orNull(draft.language);
  if (language !== (meta.language ?? null)) patch.language = language;

  if (form) {
    const stored = meta.properties ?? {};
    const props = collectProperties(form, draft.properties, stored);
    if (!props.ok) return { ok: false, invalid: props.invalid.map((n) => `properties.${n}`) };
    if (stable(props.value) !== stable(stored)) patch.properties = props.value;
  }

  const changes: MetaChanges = { patch };
  const tags = parseTags(draft.tags);
  if (stable(tags) !== stable(meta.tags)) changes.tags = tags;
  return { ok: true, changes };
}

/** Form control a server `field` (`properties.owner[0]`) points at. */
export function fieldKey(field: string | null): string | null {
  if (!field) return null;
  const m = field.match(/^properties\.([^.[]+)/);
  return m ? `properties.${m[1]}` : field;
}
