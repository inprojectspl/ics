import type { HygieneList } from "../../api/types";
import type { MessageKey } from "../../lib/i18n";

export interface ListInfo {
  key: HygieneList;
  label: MessageKey;
  hint: MessageKey;
  /** Shown only when the server reports a counter for it. */
  optional?: boolean;
}

// Keyed by list, so a new `HygieneList` member fails the type check here; order is display order.
const LIST_INFO: Readonly<Record<HygieneList, ListInfo>> = {
  no_summary: { key: "no_summary", label: "hygiene.listNoSummary", hint: "hygiene.hintNoSummary" },
  summary_stale: { key: "summary_stale", label: "hygiene.listSummaryStale", hint: "hygiene.hintSummaryStale" },
  no_doc_type: { key: "no_doc_type", label: "hygiene.listNoDocType", hint: "hygiene.hintNoDocType" },
  review_overdue: { key: "review_overdue", label: "hygiene.listReviewOverdue", hint: "hygiene.hintReviewOverdue" },
  basis_changed: { key: "basis_changed", label: "hygiene.listBasisChanged", hint: "hygiene.hintBasisChanged" },
  superseded_linked: {
    key: "superseded_linked",
    label: "hygiene.listSupersededLinked",
    hint: "hygiene.hintSupersededLinked",
  },
  hidden_edges: { key: "hidden_edges", label: "hygiene.listHiddenEdges", hint: "hygiene.hintHiddenEdges" },
  duplicates: { key: "duplicates", label: "hygiene.listDuplicates", hint: "hygiene.hintDuplicates", optional: true },
};

export const HYGIENE_LISTS: readonly ListInfo[] = Object.values(LIST_INFO);

export function parseHygieneList(raw: string | null): HygieneList {
  return raw && Object.hasOwn(LIST_INFO, raw) ? (raw as HygieneList) : "no_summary";
}

export function listInfo(key: HygieneList): ListInfo {
  return LIST_INFO[key];
}
