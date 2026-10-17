import type { ReactNode } from "react";
import { LocateFixed } from "lucide-react";

import { DocTypeBadge, FreshnessBadge } from "../../components/AssetMetaBadges";
import { AppLink } from "../../components/ui/AppLink";
import { Button, buttonClass } from "../../components/ui/Button";
import { IconButton } from "../../components/ui/IconButton";
import { t, tn } from "../../lib/i18n";
import { relationLabelKey } from "../../lib/relationLabels";
import { itemHref, itemTitle, type ExploredTree, type TreeNode } from "./explorerTree";

interface Props {
  tree: ExploredTree;
  selectedId: string | null;
  pending: ReadonlySet<string>;
  onSelect: (id: string) => void;
  onExpand: (id: string) => void;
  onCollapse: (id: string) => void;
  onReroot: (slug: string) => void;
  /** The list of loaded cards, under the details. */
  children?: ReactNode;
}

function ReachedFrom({ tree, node, onSelect }: { tree: ExploredTree; node: TreeNode; onSelect: (id: string) => void }) {
  const parentId = node.parent;
  const parent = parentId === null ? undefined : tree.nodes.get(parentId);
  if (parentId === null || !parent || parent.item.kind === "more") return null;
  const via = node.via;
  const label = via
    ? t(relationLabelKey(via.relation_type, via.source_id === node.item.id ? "out" : "in"))
    : t("graphExplorer.projectKicker");
  return (
    <p className="mt-1 truncate text-meta text-text-secondary">
      <span className="text-text-tertiary">{t("graphExplorer.reachedFrom")}</span> {label}:{" "}
      <button
        type="button"
        onClick={() => onSelect(parentId)}
        className="text-text-primary underline-offset-2 hover:text-accent hover:underline"
      >
        {itemTitle(parent.item)}
      </button>
    </p>
  );
}

/**
 * Details of the selected card and what can be done with it, kept to a few
 * lines so the list of loaded cards under it gets the height.
 */
export function ExplorerPanel({ tree, selectedId, pending, onSelect, onExpand, onCollapse, onReroot, children }: Props) {
  const node = selectedId ? tree.nodes.get(selectedId) : undefined;
  const item = node?.item;
  return (
    <div className="flex h-full min-h-0 flex-col bg-surface">
      {/* Right padding leaves room for the panel's minimise button. */}
      <div className="shrink-0 border-b border-border py-3 pl-4 pr-11">
        {!node || !item || item.kind === "more" ? (
          <p className="py-1 text-meta text-text-tertiary">{t("graphExplorer.noSelection")}</p>
        ) : (
          <section aria-label={t("graphExplorer.panelLabel", { title: itemTitle(item) })}>
            <h2 className="line-clamp-2 break-words text-ui font-semibold text-text-primary">{itemTitle(item)}</h2>
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              {item.kind === "project" ? (
                <span className="text-meta text-text-secondary">
                  {t("graphExplorer.projectKicker")} · {tn("format.documentCount", item.documents)}
                </span>
              ) : (
                <>
                  {item.doc_type && <DocTypeBadge docType={item.doc_type} />}
                  <FreshnessBadge freshness={item.freshness} />
                  {!item.expandable && <span className="text-meta text-text-tertiary">{t("graphExplorer.stateLeaf")}</span>}
                </>
              )}
            </div>
            <ReachedFrom tree={tree} node={node} onSelect={onSelect} />
            <div className="mt-2.5 flex items-center gap-1.5">
              <AppLink
                href={itemHref(item)}
                className={buttonClass("primary", "sm")}
              >
                {t("graphExplorer.open")}
              </AppLink>
              {node.expanded ? (
                <Button variant="secondary" size="sm" onClick={() => onCollapse(node.item.id)}>
                  {t("graphExplorer.collapse")}
                </Button>
              ) : (
                (item.kind === "project" || item.expandable) && (
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={pending.has(item.id)}
                    onClick={() => onExpand(item.id)}
                  >
                    {t("graphExplorer.expand")}
                  </Button>
                )
              )}
              {item.kind === "doc" && item.expandable && (
                <IconButton
                  size="sm"
                  label={t("graphExplorer.showFromHere")}
                  icon={<LocateFixed size={15} aria-hidden />}
                  onClick={() => onReroot(item.slug)}
                />
              )}
            </div>
          </section>
        )}
      </div>
      {children}
    </div>
  );
}
