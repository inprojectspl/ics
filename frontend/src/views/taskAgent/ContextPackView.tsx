import type { ReactNode } from "react";
import { AlertTriangle, Scissors } from "lucide-react";

import type { ContextPack } from "../../api";
import { t, tn } from "../../lib/i18n";
import { relationLabelKey } from "../../lib/relationLabels";
import { ContextDocumentRow } from "./ContextDocumentRow";
import { truncatedHint, warningText } from "./via";

interface Props {
  pack: ContextPack;
  budget: number;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mb-8">
      <h2 className="text-h3 font-semibold text-text-primary mb-3">{title}</h2>
      {children}
    </section>
  );
}

/** The context pack as the agent gets it: order, reasons, cuts and warnings. */
export function ContextPackView({ pack, budget }: Props) {
  const readCost = pack.documents.reduce(
    (sum, d) => sum + (d.collapsed ? 0 : (d.estimated_tokens ?? 0)),
    0,
  );
  const truncated = pack.truncated;
  return (
    <div>
      <dl className="mb-6 grid gap-3 sm:grid-cols-3">
        {[
          { label: t("taskAgent.documents"), value: String(pack.documents.length) },
          { label: t("taskAgent.packCost"), value: t("taskAgent.packCostValue", { used: pack.estimated_tokens, budget }) },
          { label: t("taskAgent.readAll"), value: tn("taskAgent.readCost", readCost) },
        ].map((s) => (
          <div key={s.label} className="rounded-control border border-border bg-surface px-3 py-2">
            <dt className="text-meta text-text-secondary font-medium">{s.label}</dt>
            <dd className="font-code text-body text-text-primary tabular-nums">{s.value}</dd>
          </div>
        ))}
      </dl>

      {pack.project === null && (
        <p className="mb-4 text-ui text-text-secondary">{t("taskAgent.noProject")}</p>
      )}
      {pack.hidden_count !== undefined && pack.hidden_count > 0 && (
        <p className="mb-4 text-ui text-text-secondary">{tn("taskAgent.hidden", pack.hidden_count)}</p>
      )}

      {truncated && (
        <div role="status" className="mb-4 flex gap-3 rounded-control border border-warning/40 bg-warning/10 px-3 py-2">
          <Scissors aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
          <div className="text-ui text-text-primary">
            <p className="font-medium">
              {t("taskAgent.truncated", {
                documents: truncated.documents,
                neighbours: truncated.neighbours,
              })}
            </p>
            <p className="mt-1 text-text-secondary">{truncatedHint(truncated)}</p>
          </div>
        </div>
      )}

      {pack.warnings.length > 0 && (
        <div className="mb-6 rounded-control border border-danger/30 bg-danger/5 px-3 py-2">
          <h2 className="flex items-center gap-2 text-ui font-medium text-danger">
            <AlertTriangle aria-hidden className="h-4 w-4" />
            {t("taskAgent.warnings")}
          </h2>
          <ul className="mt-1 list-disc pl-6 text-ui text-text-primary">
            {pack.warnings.map((w, i) => (
              <li key={`${i}:${w.code}`}>{warningText(w)}</li>
            ))}
          </ul>
        </div>
      )}

      <Section title={t("taskAgent.documents")}>
        {pack.documents.length === 0 ? (
          <p className="text-text-secondary">{t("taskAgent.empty")}</p>
        ) : (
          <ol className="space-y-2">
            {pack.documents.map((d, i) => (
              <ContextDocumentRow key={d.slug} doc={d} position={i + 1} />
            ))}
          </ol>
        )}
      </Section>

      {pack.edges.length > 0 && (
        <Section title={t("taskAgent.edges")}>
          <ul className="space-y-1 text-ui">
            {pack.edges.map(([from, type, to, extra]) => (
              <li key={`${from}|${type}|${to}`} className="flex flex-wrap items-center gap-2">
                <span className="font-code text-text-primary">{from}</span>
                <span className="text-text-secondary">{t(relationLabelKey(type, "out"))}</span>
                <span className="font-code text-text-primary">
                  {to}
                  {extra?.target_anchor && `#${extra.target_anchor}`}
                </span>
                {extra?.changed && (
                  <span className="text-warning">
                    {t("relations.basisChanged", { from: extra.changed[0], to: extra.changed[1] })}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}
