/**
 * Visual encoding of the document graph (ADR-0015, ADR-0016). Colours are
 * mid-tones readable on both themes; an unknown doc type gets the neutral
 * fallback rather than a colour that could collide with a known one.
 */
import type {
  DocType,
  Freshness,
  RelationEdge,
  RelationOrigin,
  RelationType,
} from "../../api/types";
import { t } from "../../lib/i18n";
import { relationLabelKey } from "../../lib/relationLabels";
import type { CardEdge, CardNode } from "./cardTypes";
import type { EdgeStyle } from "./types";

/** What a card needs from a project graph or neighbourhood node. */
export interface DocumentCardInput {
  id: string;
  slug: string;
  title: string | null;
  doc_type: DocType | null;
  freshness: Freshness;
  summary?: string | null;
  external?: boolean;
}

export type { RelationOrigin, RelationType };

/** Fill of a node without a doc type or with one the palette does not know. */
export const DOC_TYPE_FALLBACK_COLOR = "#8a8f98";

// Related types share a hue family: goals/requirements warm, design/spec blue-violet,
// knowledge teal/cyan, commercial rose, operations green.
// A Map, not an object: doc type keys are data, and "constructor" must not hit the prototype.
const DOC_TYPE_COLORS: ReadonlyMap<string, string> = new Map(
  Object.entries({
    business_goals: "#b45309",
    requirements: "#ea580c",
    design: "#7c3aed",
    specification: "#2563eb",
    decision: "#0f766e",
    research: "#0891b2",
    report: "#65a30d",
    meeting_notes: "#a16207",
    contract: "#be123c",
    offer: "#db2777",
    manual: "#15803d",
    runbook: "#059669",
    policy: "#4338ca",
    presentation: "#c026d3",
  }),
);

export function docTypeColor(docType: DocType | null | undefined): string {
  return (docType != null && DOC_TYPE_COLORS.get(docType)) || DOC_TYPE_FALLBACK_COLOR;
}

// Every type has its own colour so the legend can name it; the traceability
// chain (derived from, depends on, supersedes) is drawn widest, weak links dashed.
const RELATION_STYLES: Readonly<Record<RelationType, EdgeStyle>> = {
  derived_from: { color: "#3b82f6", width: 1.6 },
  depends_on: { color: "#0d9488", width: 1.6 },
  supersedes: { color: "#a855f7", width: 1.6 },
  part_of: { color: "#d97706", width: 1.4 },
  references: { color: "#8b9bb4", width: 1.2 },
  relates_to: { color: "#8b9bb4", width: 1.2, dashed: true },
  duplicates: { color: "#db2777", width: 1.3, dashed: true },
  contradicts: { color: "#ef4444", width: 1.6, dashed: true },
};

/**
 * Relations that put their target (the origin) on a layer before the source:
 * the basis above what is derived from it. The other types are not ordered.
 */
export const LAYER_RELATIONS: ReadonlySet<string> = new Set<RelationType>([
  "derived_from",
  "depends_on",
  "part_of",
  "supersedes",
  "references",
]);

/** Extracted edges (from links in the content) are drawn at this share of the width. */
export const EXTRACTED_WIDTH_FACTOR = 0.5;

export function documentEdgeStyle(relation: RelationType, origin?: RelationOrigin): EdgeStyle {
  const base = RELATION_STYLES[relation];
  if (origin !== "extracted") return { ...base };
  return { ...base, width: (base.width ?? 1) * EXTRACTED_WIDTH_FACTOR };
}

/** A document as a card; `typeLabel` names its doc type in the UI locale. */
export function documentCard(
  n: DocumentCardInput,
  component: number,
  typeLabel: (docType: DocType | null) => string,
): CardNode {
  const card: CardNode = {
    id: n.id,
    title: n.title || n.slug,
    kicker: typeLabel(n.doc_type),
    color: docTypeColor(n.doc_type),
    component,
  };
  if (n.summary) card.sub = n.summary;
  if (n.freshness === "review_overdue") card.badge = { text: t("freshness.reviewOverdue"), tone: "warn" };
  else if (n.freshness === "superseded") {
    card.badge = { text: t("freshness.superseded"), tone: "mute" };
    card.muted = true;
  } else if (n.external) card.badge = { text: t("projectMap.external"), tone: "info" };
  if (n.external) card.dashed = true;
  return card;
}

/** A relation edge from the API as a card edge, styled by type and origin. */
export function relationCardEdge(
  e: Pick<RelationEdge, "id" | "source_id" | "target_id" | "relation_type" | "origin">,
): CardEdge {
  const style = documentEdgeStyle(e.relation_type, e.origin);
  return {
    id: e.id,
    source: e.source_id,
    target: e.target_id,
    kind: e.relation_type,
    color: style.color,
    width: style.width ?? 1,
    dashed: style.dashed,
    label: t(relationLabelKey(e.relation_type, "out")),
  };
}
