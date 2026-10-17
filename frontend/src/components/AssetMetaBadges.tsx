import { clsx } from "clsx";

import type { DocType, Freshness } from "../api";
import { t, type MessageKey } from "../lib/i18n";
import { useDocTypeLabels } from "../lib/useDocTypes";
import { docTypeColor } from "./graph";

/** Shared by the list badge and the sidebar facet labels. */
export const FRESHNESS_LABEL: Record<Freshness, MessageKey> = {
  current: "freshness.current",
  review_overdue: "freshness.reviewOverdue",
  superseded: "freshness.superseded",
};

/**
 * Doc type pill with the colour the document graph uses for the same type.
 * The label comes from the doc type catalogue; `label` is only a fallback for
 * a key the catalogue does not know (yet), before the key itself.
 */
export function DocTypeBadge({ docType, label: fallback }: { docType: DocType; label?: string }) {
  const label = useDocTypeLabels().get(docType) ?? fallback ?? docType;
  return (
    <span
      className="shrink-0 inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-text-primary/[0.05] text-meta text-text-secondary max-w-[10rem]"
      title={t("assetRow.docTypeTitle", { label })}
    >
      <span
        aria-hidden
        className="h-1.5 w-1.5 shrink-0 rounded-full"
        style={{ backgroundColor: docTypeColor(docType) }}
      />
      <span className="truncate">{label}</span>
    </span>
  );
}

/** Nothing for `current`: only a reason to doubt the document gets weight. */
export function FreshnessBadge({ freshness }: { freshness: Freshness | null | undefined }) {
  if (!freshness || freshness === "current") return null;
  const overdue = freshness === "review_overdue";
  return (
    <span
      className={clsx(
        "shrink-0 inline-flex items-center px-2 py-0.5 rounded-full text-meta",
        overdue ? "bg-warning/15 text-warning" : "bg-text-primary/[0.05] text-text-tertiary line-through",
      )}
      title={t(overdue ? "freshness.reviewOverdueTitle" : "freshness.supersededTitle")}
    >
      {t(FRESHNESS_LABEL[freshness])}
    </span>
  );
}
