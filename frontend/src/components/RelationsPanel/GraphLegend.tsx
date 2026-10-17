import { RELATION_TYPES } from "../../api/relationTypes";
import { t } from "../../lib/i18n";
import { relationLabelKey } from "../../lib/relationLabels";
import type { CardEdge, CardNode } from "../graph";
import { RelationSwatch } from "../graph/RelationLegend";

interface Props {
  cards: readonly CardNode[];
  edges: readonly CardEdge[];
}

/** What the stripe colours (doc types) and the line styles (relation types) of a small graph mean. */
export function GraphLegend({ cards, edges }: Props) {
  const types = new Map<string, string>();
  for (const c of cards) if (c.kicker && !types.has(c.kicker)) types.set(c.kicker, c.color);
  const drawn = new Set(edges.map((e) => e.kind));
  const relations = RELATION_TYPES.filter((r) => drawn.has(r));
  if (types.size === 0 && relations.length === 0) return null;

  return (
    <dl aria-label={t("cardGraph.legend")} className="mt-2 grid gap-1.5 text-meta text-text-secondary">
      {types.size > 0 && (
        <div>
          <dt className="sr-only">{t("miniGraph.legendDocTypes")}</dt>
          <dd className="flex flex-wrap gap-x-3 gap-y-1">
            {[...types].map(([label, color]) => (
              <span key={label} className="inline-flex items-center gap-1.5">
                <span aria-hidden className="inline-block h-2.5 w-1.5 rounded-full" style={{ backgroundColor: color }} />
                {label}
              </span>
            ))}
          </dd>
        </div>
      )}
      {relations.length > 0 && (
        <div>
          <dt className="sr-only">{t("miniGraph.legendRelations")}</dt>
          <dd className="flex flex-wrap gap-x-3 gap-y-1">
            {relations.map((r) => (
              <span key={r} className="inline-flex items-center gap-1.5">
                <RelationSwatch type={r} />
                {t(relationLabelKey(r, "out"))}
              </span>
            ))}
          </dd>
        </div>
      )}
    </dl>
  );
}
