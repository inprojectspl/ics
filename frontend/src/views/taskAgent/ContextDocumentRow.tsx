import { memo } from "react";

import type { ContextPackCollapsed, ContextPackDocument } from "../../api";
import { DocTypeBadge, FreshnessBadge } from "../../components/AssetMetaBadges";
import { agentViewHref } from "../../lib/agentView";
import { t, tn } from "../../lib/i18n";
import { viaText } from "./via";

const PILL = "shrink-0 inline-flex items-center px-2 py-0.5 rounded-full text-meta";

function Position({ n }: { n: number }) {
  return (
    <span className="w-8 shrink-0 pt-0.5 text-right font-code text-ui text-text-tertiary tabular-nums">
      {n}.
    </span>
  );
}

function Title({ slug, title }: { slug: string; title: string | null }) {
  return (
    <a href={`/v/${slug}`} className="font-medium text-text-primary hover:text-accent break-words">
      {title || slug}
    </a>
  );
}

interface Props {
  doc: ContextPackDocument | ContextPackCollapsed;
  /** 1-based place in the pack: the order an agent reads in. */
  position: number;
}

/** One document of the pack with every reason it is there. */
export const ContextDocumentRow = memo(function ContextDocumentRow({ doc, position }: Props) {
  if (doc.collapsed) {
    return (
      <li className="flex gap-3 rounded-control border border-border px-3 py-2 opacity-80">
        <Position n={position} />
        <div className="min-w-0 flex-1 flex flex-wrap items-center gap-2">
          <Title slug={doc.slug} title={doc.title} />
          <FreshnessBadge freshness="superseded" />
          {doc.required && <span className={`${PILL} bg-accent/15 text-accent`}>{t("taskLinks.required")}</span>}
          <span className="text-ui text-text-secondary">
            {t("taskAgent.collapsed", { slug: doc.superseded_by })}
          </span>
        </div>
      </li>
    );
  }
  return (
    <li className="flex gap-3 rounded-control border border-border bg-surface px-3 py-3">
      <Position n={position} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <Title slug={doc.slug} title={doc.title} />
          <span className="font-code text-meta text-text-tertiary">{doc.slug}</span>
          {doc.required && <span className={`${PILL} bg-accent/15 text-accent`}>{t("taskLinks.required")}</span>}
          {doc.doc_type && (
            <DocTypeBadge docType={doc.doc_type} />
          )}
          <FreshnessBadge freshness={doc.freshness} />
          {doc.flags?.map((flag) => (
            <span key={flag} className={`${PILL} bg-warning/15 text-warning`}>
              {t(flag === "basis_changed" ? "taskAgent.flagBasisChanged" : "taskAgent.flagSummaryStale")}
            </span>
          ))}
        </div>
        <ul className="mt-1.5 flex flex-wrap gap-1.5" aria-label={t("taskAgent.via")}>
          {doc.via.map((via, i) => (
            <li key={i} className={`${PILL} bg-text-primary/[0.05] text-text-secondary`}>
              {viaText(via)}
            </li>
          ))}
        </ul>
        {doc.summary && <p className="mt-1.5 text-ui text-text-secondary">{doc.summary}</p>}
        <p className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-meta text-text-tertiary">
          <span>v{doc.version}</span>
          {doc.estimated_tokens !== undefined && (
            <span>{tn("taskAgent.readCost", doc.estimated_tokens)}</span>
          )}
          {doc.has_outline === false && <span>{t("taskAgent.noOutline")}</span>}
          <a href={agentViewHref(doc.slug, {})} className="text-accent hover:underline">
            {t("taskAgent.whatAgentReads")}
          </a>
        </p>
      </div>
    </li>
  );
});
