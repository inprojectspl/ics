import { X } from "lucide-react";

import type { ProjectGraphNode, ProjectTask, ProjectTaskLink, RelationEdge } from "../../api/types";
import { DocTypeBadge, FreshnessBadge } from "../../components/AssetMetaBadges";
import { buttonClass } from "../../components/ui/Button";
import { refNumber, safeUrl } from "../../components/TaskLinks/taskRef";
import { formatNumber, t } from "../../lib/i18n";
import { formatShortDate } from "../../lib/format";
import { relationLabelKey } from "../../lib/relationLabels";

interface Props {
  node: ProjectGraphNode;
  nodesById: ReadonlyMap<string, ProjectGraphNode>;
  edges: RelationEdge[];
  tasks: ProjectTask[];
  links: ProjectTaskLink[];
  onSelect: (id: string) => void;
  onClose: () => void;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-5">
      <h3 className="text-meta text-text-secondary mb-2 font-medium">{title}</h3>
      {children}
    </section>
  );
}

/** Details of the node picked on the canvas or in the node list. */
export function NodePanel({ node, nodesById, edges, tasks, links, onSelect, onClose }: Props) {
  const touching = edges.filter((e) => e.source_id === node.id || e.target_id === node.id);
  const taskById = new Map(tasks.map((x) => [x.id, x]));
  const nodeTasks = links.filter((l) => l.asset_id === node.id);
  const title = node.title || node.slug;
  return (
    <aside
      aria-label={t("projectMap.panelLabel", { title })}
      className="min-h-full bg-surface p-5"
    >
      <div className="flex items-start gap-2">
        <h2 className="text-h3 font-semibold text-text-primary break-words flex-1 min-w-0">{title}</h2>
        <button
          type="button"
          onClick={onClose}
          aria-label={t("common.close")}
          className="shrink-0 inline-flex items-center justify-center w-8 h-8 rounded-full text-text-tertiary hover:text-text-primary hover:bg-surface-subtle"
        >
          <X size={16} aria-hidden />
        </button>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {node.doc_type && (
          <DocTypeBadge docType={node.doc_type} />
        )}
        <FreshnessBadge freshness={node.freshness} />
        {node.external && (
          <span className="px-2 py-0.5 rounded-full border border-dashed border-border text-meta text-text-tertiary">
            {t("projectMap.externalLong")}
          </span>
        )}
      </div>

      <p className="mt-4 text-ui text-text-secondary">{node.summary || t("assetMeta.noSummary")}</p>

      <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-meta text-text-tertiary">
        {node.content_updated_at && (
          <>
            <dt>{t("projectMap.updated")}</dt>
            <dd className="text-text-secondary">{formatShortDate(node.content_updated_at)}</dd>
          </>
        )}
        {node.estimated_tokens != null && (
          <>
            <dt>{t("projectMap.tokens")}</dt>
            <dd className="text-text-secondary">{formatNumber(node.estimated_tokens)}</dd>
          </>
        )}
      </dl>

      <Section title={t("projectMap.relations", { count: touching.length })}>
        {touching.length === 0 ? (
          <p className="text-ui text-text-tertiary">{t("projectMap.noRelations")}</p>
        ) : (
          <ul className="space-y-2.5">
            {touching.map((e) => {
              const out = e.source_id === node.id;
              const other = nodesById.get(out ? e.target_id : e.source_id);
              return (
                <li key={e.id} className="min-w-0">
                  <div className="text-meta text-text-tertiary">{t(relationLabelKey(e.relation_type, out ? "out" : "in"))}</div>
                  {other ? (
                    <button
                      type="button"
                      onClick={() => onSelect(other.id)}
                      className="block w-full text-left text-ui text-text-primary hover:text-accent underline-offset-2 hover:underline"
                    >
                      {other.title || other.slug}
                    </button>
                  ) : (
                    <span className="text-ui text-text-tertiary">{t("projectMap.hiddenDocument")}</span>
                  )}
                  {e.target_changed && out && (
                    <span className="text-meta text-warning">{t("assetMeta.changed")}</span>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Section>

      {nodeTasks.length > 0 && (
        <Section title={t("projectMap.tasks", { count: nodeTasks.length })}>
          <ul className="space-y-1.5">
            {nodeTasks.map((l) => {
              const task = taskById.get(l.task_id);
              const name = task ? task.label || refNumber(task) : l.task_id;
              const url = task ? safeUrl(task.url) : null;
              return (
                <li key={l.task_id} className="text-ui">
                  {url ? (
                    <a href={url} target="_blank" rel="noreferrer" className="text-text-primary hover:text-accent">
                      {name}
                    </a>
                  ) : (
                    <span className="text-text-primary">{name}</span>
                  )}
                  {l.required && <span className="ml-1 text-text-tertiary">({t("projectMap.required")})</span>}
                </li>
              );
            })}
          </ul>
        </Section>
      )}

      <a href={`/v/${node.slug}`} className={`${buttonClass("primary", "sm")} mt-6 w-full`}>
        {t("common.open")}
      </a>
    </aside>
  );
}
