import type { ReactNode } from "react";

import type { RelationType } from "../../api/types";
import { t } from "../../lib/i18n";
import { relationLabelKey } from "../../lib/relationLabels";
import { documentEdgeStyle } from "./documentStyles";

/** Short line sample in an edge colour. */
export function RelationLine({ color, dashed }: { color: string; dashed: boolean }) {
  return (
    <span
      aria-hidden
      className="inline-block w-4 shrink-0 border-t-2"
      style={{ borderColor: color, borderStyle: dashed ? "dashed" : "solid" }}
    />
  );
}

/** Line sample of a relation type in its graph colour. */
export function RelationSwatch({ type }: { type: RelationType }) {
  const style = documentEdgeStyle(type);
  return <RelationLine color={style.color ?? "currentColor"} dashed={!!style.dashed} />;
}

/** Colours of the relation types drawn on a graph; `extra` adds items after them. */
export function RelationLegend({ types, extra }: { types: readonly RelationType[]; extra?: ReactNode }) {
  if (types.length === 0 && !extra) return null;
  return (
    <ul
      aria-label={t("cardGraph.legend")}
      className="ml-auto flex flex-wrap items-center gap-x-4 gap-y-1 text-meta text-text-secondary"
    >
      {types.map((r) => (
        <li key={r} className="flex items-center gap-1.5">
          <RelationSwatch type={r} />
          {t(relationLabelKey(r, "out"))}
        </li>
      ))}
      {extra}
    </ul>
  );
}
