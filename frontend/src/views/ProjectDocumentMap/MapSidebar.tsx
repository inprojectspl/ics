import type { Freshness, RelationType } from "../../api/types";
import { FRESHNESS_LABEL } from "../../components/AssetMetaBadges";
import { SearchInput } from "../../components/SearchInput";
import { PanelSection } from "../../components/ui/PanelSection";
import { docTypeColor } from "../../components/graph";
import { t } from "../../lib/i18n";
import { useDocTypeLabel } from "../../lib/useDocTypes";
import { relationLabelKey } from "../../lib/relationLabels";
import type { MapFilters } from "./filters";
import { RelationSwatch } from "../../components/graph/RelationLegend";

const FRESHNESS: Freshness[] = ["current", "review_overdue", "superseded"];

interface Props {
  filters: MapFilters;
  onChange: (next: MapFilters) => void;
  /** Doc type keys present in the graph (`NO_DOC_TYPE` for untyped). */
  docTypes: string[];
  relationTypes: RelationType[];
  hasTasks: boolean;
  showTasks: boolean;
  onShowTasks: (on: boolean) => void;
  /** Document lists, placed between the filters and the legend. */
  children?: React.ReactNode;
}

function toggled<T>(set: ReadonlySet<T>, value: T): Set<T> {
  const next = new Set(set);
  if (next.has(value)) next.delete(value);
  else next.add(value);
  return next;
}

function Check({
  checked,
  onChange,
  children,
}: {
  checked: boolean;
  onChange: () => void;
  children: React.ReactNode;
}) {
  return (
    <label className="flex items-center gap-2 px-1 py-1 text-ui text-text-secondary hover:text-text-primary cursor-pointer">
      <input type="checkbox" checked={checked} onChange={onChange} className="accent-accent" />
      {children}
    </label>
  );
}

function Swatch({ color, dashed = false }: { color: string; dashed?: boolean }) {
  return (
    <span
      aria-hidden
      className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
      style={{ backgroundColor: color, outline: dashed ? "1px dashed currentColor" : undefined }}
    />
  );
}

/** Filters, layers and the legend of the document map (the toolbar popover). */
export function MapSidebar(props: Props) {
  const { filters, onChange, docTypes, relationTypes } = props;
  const typeLabel = useDocTypeLabel();
  const set = (over: Partial<MapFilters>) => onChange({ ...filters, ...over, component: null });
  return (
    <>
      <PanelSection title={t("projectMap.search")}>
        <SearchInput
          value={filters.search}
          onChange={(search) => set({ search })}
          ariaLabel={t("projectMap.search")}
          placeholder={t("projectMap.searchPlaceholder")}
        />
      </PanelSection>

      <PanelSection title={t("projectMap.docType")}>
        {docTypes.map((key) => (
          <Check key={key} checked={filters.docTypes.has(key)} onChange={() => set({ docTypes: toggled(filters.docTypes, key) })}>
            <Swatch color={docTypeColor(key || null)} />
            {typeLabel(key)}
          </Check>
        ))}
      </PanelSection>

      <PanelSection title={t("projectMap.freshness")}>
        {FRESHNESS.map((f) => (
          <Check key={f} checked={filters.freshness.has(f)} onChange={() => set({ freshness: toggled(filters.freshness, f) })}>
            {t(FRESHNESS_LABEL[f])}
          </Check>
        ))}
      </PanelSection>

      <PanelSection title={t("projectMap.relationType")}>
        {relationTypes.map((r) => (
          <Check
            key={r}
            checked={filters.relationTypes.has(r)}
            onChange={() => set({ relationTypes: toggled(filters.relationTypes, r) })}
          >
            <RelationSwatch type={r} />
            {t(relationLabelKey(r, "out"))}
          </Check>
        ))}
      </PanelSection>

      {props.hasTasks && (
        <PanelSection title={t("projectMap.tasksSection")}>
          <Check checked={filters.onlyTaskDocs} onChange={() => set({ onlyTaskDocs: !filters.onlyTaskDocs })}>
            {t("projectMap.onlyTaskDocs")}
          </Check>
          <Check checked={props.showTasks} onChange={() => props.onShowTasks(!props.showTasks)}>
            {t("projectMap.taskLayer")}
          </Check>
        </PanelSection>
      )}

      {props.children}

      <PanelSection title={t("projectMap.legend")} last>
        <ul className="space-y-1.5 text-meta text-text-secondary">
          <li className="flex items-center gap-2">
            <Swatch color={docTypeColor(null)} dashed />
            {t("projectMap.legendExternal")}
          </li>
          <li className="flex items-center gap-2">
            <Swatch color={docTypeColor(null)} />
            <span className="line-through">{t("freshness.superseded")}</span>
            <span className="text-text-tertiary">{t("projectMap.legendFaded")}</span>
          </li>
          <li className="text-text-tertiary">{t("projectMap.legendHint")}</li>
        </ul>
      </PanelSection>
    </>
  );
}
