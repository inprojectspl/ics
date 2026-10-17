import type { RelationDirection, RelationLabel, RelationType } from "../api";
import type { MessageKey } from "./i18n";

/** Catalogue key of every relation label, outgoing types and their inverses alike. */
export const RELATION_LABEL: Record<RelationLabel, MessageKey> = {
  derived_from: "relation.derivedFrom",
  basis_for: "relation.basisFor",
  supersedes: "relation.supersedes",
  superseded_by: "relation.supersededBy",
  depends_on: "relation.dependsOn",
  required_by: "relation.requiredBy",
  part_of: "relation.partOf",
  has_part: "relation.hasPart",
  references: "relation.references",
  referenced_by: "relation.referencedBy",
  duplicates: "relation.duplicates",
  duplicated_by: "relation.duplicatedBy",
  relates_to: "relation.relatesTo",
  contradicts: "relation.contradicts",
};

// Symmetric types are their own inverse.
const INVERSE: Record<RelationType, RelationLabel> = {
  derived_from: "basis_for",
  supersedes: "superseded_by",
  depends_on: "required_by",
  part_of: "has_part",
  references: "referenced_by",
  duplicates: "duplicated_by",
  relates_to: "relates_to",
  contradicts: "contradicts",
};

/**
 * Catalogue key of a relation as read from one end: `out` from the source
 * ("derived from"), `in` from the target ("basis for").
 */
export function relationLabelKey(type: RelationType, direction: RelationDirection): MessageKey {
  return RELATION_LABEL[direction === "out" ? type : INVERSE[type]];
}
