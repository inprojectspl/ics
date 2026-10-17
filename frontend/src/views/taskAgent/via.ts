import type {
  ContextPackTruncated,
  ContextPackWarning,
  ContextVia,
  RelationLabel,
  RelationType,
} from "../../api";
import { ROLE_LABEL } from "../../components/TaskLinks/taskRef";
import { t, type MessageKey } from "../../lib/i18n";
import { relationLabelKey } from "../../lib/relationLabels";

/** Relation type behind each inverse label (`basis_for` is `derived_from` read from its target). */
const INVERSE_OF: Partial<Record<RelationLabel, RelationType>> = {
  basis_for: "derived_from",
  superseded_by: "supersedes",
  required_by: "depends_on",
  has_part: "part_of",
  referenced_by: "references",
  duplicated_by: "duplicates",
};

/** Label of a neighbour edge as read from the document it was reached from. */
function labelKey(label: RelationLabel): MessageKey {
  const inverse = INVERSE_OF[label];
  return inverse ? relationLabelKey(inverse, "in") : relationLabelKey(label as RelationType, "out");
}

/** One way a document got into the pack, as a sentence fragment. */
export function viaText(via: ContextVia): string {
  switch (via.kind) {
    case "direct":
      return t("taskAgent.viaDirect", { role: t(ROLE_LABEL[via.role]) });
    case "inherited":
      return t("taskAgent.viaInherited", { role: t(ROLE_LABEL[via.role]), wp: via.wp });
    case "project_key":
      return via.reason
        ? t("taskAgent.viaKeyReason", { reason: via.reason })
        : t("taskAgent.viaKey");
    case "successor_of":
      return t("taskAgent.viaSuccessor", { slug: via.slug });
    case "neighbour":
      return t("taskAgent.viaNeighbour", { relation: t(labelKey(via.type)), slug: via.from });
  }
}

/** A server warning worded for the reader. */
export function warningText(w: ContextPackWarning): string {
  switch (w.code) {
    case "superseded":
      return t(w.params.required ? "taskAgent.warningSupersededRequired" : "taskAgent.warningSuperseded", {
        slug: w.params.slug,
        successor: w.params.successor,
      });
    case "basis_changed":
      return t("taskAgent.warningBasisChanged", { slug: w.params.slug });
    case "contradicts":
      return t("taskAgent.warningContradicts", { from: w.params.from, to: w.params.to });
    case "project_unmapped":
      return t("taskAgent.warningProjectUnmapped", { project: w.params.project });
    case "task_unlinked":
      return t("taskAgent.warningTaskUnlinked", { wp: w.params.wp });
  }
}

/** How to get what the budget cut: a larger budget while the whole pack fits the maximum. */
export function truncatedHint(cut: ContextPackTruncated): string {
  if (cut.needed_tokens <= cut.max_budget_tokens) {
    return t("taskAgent.truncatedRaise", { budget: cut.needed_tokens });
  }
  const over = { needed: cut.needed_tokens, max: cut.max_budget_tokens };
  return cut.seed
    ? t("taskAgent.truncatedNeighbourhood", { ...over, seed: cut.seed })
    : t("taskAgent.truncatedNarrow", over);
}
