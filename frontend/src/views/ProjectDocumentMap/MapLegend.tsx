import type { RelationType } from "../../api/types";
import { RelationLegend, RelationLine } from "../../components/graph/RelationLegend";
import { t } from "../../lib/i18n";
import { TASK_EDGE_COLOR } from "./model";

/** Colours of the relation types drawn on the map, plus the task link when shown. */
export function MapLegend({ types, tasks }: { types: RelationType[]; tasks: boolean }) {
  return (
    <RelationLegend
      types={types}
      extra={
        tasks && (
          <li className="flex items-center gap-1.5">
            <RelationLine color={TASK_EDGE_COLOR} dashed />
            {t("projectMap.legendTask")}
          </li>
        )
      }
    />
  );
}
