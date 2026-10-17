import { memo } from "react";
import { AlertTriangle, X } from "lucide-react";

import type { RelationDirection, RelationItem, RelationOrigin } from "../../api";
import { t, type MessageKey } from "../../lib/i18n";
import { DocTypeBadge, FreshnessBadge } from "../AssetMetaBadges";

const ORIGIN_LABEL: Record<RelationOrigin, MessageKey> = {
  manual: "relations.originManual",
  agent: "relations.originAgent",
  extracted: "relations.originExtracted",
  integration: "relations.originIntegration",
};

interface Props {
  item: RelationItem;
  direction: RelationDirection;
  canEdit: boolean;
  busy: boolean;
  onConfirmCurrent: (relationId: string) => void;
  onRemove: (relationId: string) => void;
}

function RelationRowImpl({
  item,
  direction,
  canEdit,
  busy,
  onConfirmCurrent,
  onRemove,
}: Props) {
  const other = item.other;
  const title = other.title ?? other.slug;
  // The warning belongs to the side that was built on the target. Only
  // `derived_from` makes the target a basis (ADR-0016 §7); the Hygiene
  // `basis_changed` flag counts the same edges.
  const basisChanged = direction === "out" && item.relation_type === "derived_from" && item.target_changed;
  const from = item.target_version;
  const to = item.target_version_now;
  return (
    <li className="py-2 border-b border-border last:border-b-0">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 flex-wrap">
            <a
              href={`/v/${other.slug}`}
              className="text-ui text-text-primary hover:text-accent truncate max-w-full"
            >
              {title}
            </a>
            {other.doc_type && (
              <DocTypeBadge docType={other.doc_type} />
            )}
            <FreshnessBadge freshness={other.freshness} />
          </div>
          {item.note && <p className="text-meta text-text-secondary mt-0.5 break-words">{item.note}</p>}
          <p className="text-meta text-text-tertiary mt-0.5">{t(ORIGIN_LABEL[item.origin])}</p>
        </div>
        {canEdit && (
          <button
            type="button"
            disabled={busy}
            onClick={() => onRemove(item.id)}
            aria-label={t("relations.removeLabel", { title })}
            className="shrink-0 p-1 rounded-control text-text-tertiary hover:text-danger hover:bg-danger/10 disabled:opacity-50"
          >
            <X size={14} aria-hidden />
          </button>
        )}
      </div>
      {basisChanged && from !== null && to !== null && (
        <div role="status" className="mt-1.5 rounded-control bg-warning/10 px-2 py-1.5 text-meta text-warning">
          <p className="flex items-center gap-1.5">
            <AlertTriangle size={13} aria-hidden />
            {t("relations.basisChanged", { from, to })}
          </p>
          <div className="flex gap-3 mt-1">
            <a
              href={`/v/${other.slug}/diff?from=${from}&to=${to}`}
              className="underline hover:no-underline"
            >
              {t("relations.showChanges")}
            </a>
            {canEdit && (
              <button
                type="button"
                disabled={busy}
                onClick={() => onConfirmCurrent(item.id)}
                className="underline hover:no-underline disabled:opacity-50"
              >
                {t("relations.stillCurrent")}
              </button>
            )}
          </div>
        </div>
      )}
    </li>
  );
}

export const RelationRow = memo(RelationRowImpl);
