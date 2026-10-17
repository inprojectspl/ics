import { describe, expect, it } from "vitest";

import {
  DOC_TYPE_FALLBACK_COLOR,
  EXTRACTED_WIDTH_FACTOR,
  docTypeColor,
  documentCard,
  documentEdgeStyle,
  relationCardEdge,
} from "./documentStyles";
import { t } from "../../lib/i18n";

describe("docTypeColor", () => {
  it("gives known types distinct colours and the rest the fallback", () => {
    expect(docTypeColor("design")).not.toBe(docTypeColor("specification"));
    expect(docTypeColor("design")).not.toBe(DOC_TYPE_FALLBACK_COLOR);
    expect(docTypeColor("added_by_admin")).toBe(DOC_TYPE_FALLBACK_COLOR);
    expect(docTypeColor(null)).toBe(DOC_TYPE_FALLBACK_COLOR);
    expect(docTypeColor("constructor")).toBe(DOC_TYPE_FALLBACK_COLOR);
  });
});

describe("documentEdgeStyle", () => {
  it("styles relations by type", () => {
    expect(documentEdgeStyle("derived_from").color).toBeDefined();
    expect(documentEdgeStyle("references").color).toBeDefined();
    expect(documentEdgeStyle("relates_to").dashed).toBe(true);
    expect(documentEdgeStyle("contradicts").dashed).toBe(true);
  });

  it("draws extracted edges thinner without changing the shared style", () => {
    const manual = documentEdgeStyle("references", "manual");
    const extracted = documentEdgeStyle("references", "extracted");
    expect(extracted.width).toBe((manual.width ?? 1) * EXTRACTED_WIDTH_FACTOR);
    expect(documentEdgeStyle("references").width).toBe(manual.width);
  });
});

describe("documentCard", () => {
  const label = (key: string | null) => key ?? "none";
  const base = { id: "a", slug: "sa", title: "Spec", doc_type: "specification", freshness: "current" as const };

  it("carries the title, type label and colour, falling back to the slug", () => {
    const card = documentCard({ ...base, summary: "Short" }, 2, label);
    expect(card).toMatchObject({ id: "a", title: "Spec", kicker: "specification", component: 2, sub: "Short" });
    expect(card.color).toBe(docTypeColor("specification"));
    expect(card.badge).toBeUndefined();
    expect(documentCard({ ...base, title: null }, 0, label).title).toBe("sa");
  });

  it("marks freshness with a badge and mutes a superseded document", () => {
    const overdue = documentCard({ ...base, freshness: "review_overdue" }, 0, label);
    expect(overdue.badge).toEqual({ text: t("freshness.reviewOverdue"), tone: "warn" });
    const superseded = documentCard({ ...base, freshness: "superseded" }, 0, label);
    expect(superseded.muted).toBe(true);
    expect(superseded.badge?.tone).toBe("mute");
  });

  it("draws an external document dashed", () => {
    const card = documentCard({ ...base, external: true }, 0, label);
    expect(card.dashed).toBe(true);
    expect(card.badge?.tone).toBe("info");
  });
});

describe("relationCardEdge", () => {
  it("maps ends and kind, styles by type and origin and names the relation", () => {
    const edge = relationCardEdge({
      id: "e",
      source_id: "a",
      target_id: "b",
      relation_type: "references",
      origin: "extracted",
    });
    const style = documentEdgeStyle("references", "extracted");
    expect(edge).toMatchObject({ id: "e", source: "a", target: "b", kind: "references", width: style.width });
    expect(edge.label).toBe(t("relation.references"));
  });
});
