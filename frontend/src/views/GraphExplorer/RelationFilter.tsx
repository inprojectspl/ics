import { ListFilter } from "lucide-react";

import { RELATION_TYPES, type RelationType } from "../../api/relationTypes";
import { RelationSwatch } from "../../components/graph/RelationLegend";
import { buttonClass } from "../../components/ui/Button";
import { PanelSection } from "../../components/ui/PanelSection";
import { Popover } from "../../components/ui/Popover";
import { t } from "../../lib/i18n";
import { relationLabelKey } from "../../lib/relationLabels";

interface Props {
  types: ReadonlySet<RelationType>;
  onChange: (next: ReadonlySet<RelationType>) => void;
}

/** Relation types the walk follows and draws; every type when none is left out. */
export function RelationFilter({ types, onChange }: Props) {
  const off = RELATION_TYPES.length - types.size;
  const toggle = (r: RelationType) => {
    const next = new Set(types);
    if (next.has(r)) next.delete(r);
    else next.add(r);
    onChange(next);
  };
  return (
    <Popover
      label={t("graphExplorer.relationTypes")}
      widthClass="w-[18rem]"
      trigger={(p) => (
        <button type="button" {...p} className={buttonClass("secondary")}>
          <ListFilter size={16} aria-hidden />
          {t("filters.title")}
          {off > 0 && (
            <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-accent px-1.5 text-caption font-semibold tabular-nums text-on-accent">
              {off}
            </span>
          )}
        </button>
      )}
    >
      {() => (
        <PanelSection title={t("graphExplorer.relationTypes")} last>
          {RELATION_TYPES.map((r) => (
            <label key={r} className="flex cursor-pointer items-center gap-2 px-1 py-1 text-ui text-text-secondary hover:text-text-primary">
              <input type="checkbox" checked={types.has(r)} onChange={() => toggle(r)} className="accent-accent" />
              <RelationSwatch type={r} />
              {t(relationLabelKey(r, "out"))}
            </label>
          ))}
        </PanelSection>
      )}
    </Popover>
  );
}
