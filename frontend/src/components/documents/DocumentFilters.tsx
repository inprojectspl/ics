import { useMemo, useState } from "react";
import { clsx } from "clsx";
import { ListFilter, X } from "lucide-react";
import type { ProjectSummary } from "../../api";
import { intlLocale, t, type MessageKey } from "../../lib/i18n";
import {
  FRESHNESS_VALUES,
  filterKind,
  type AssetFilter,
  type FilterCounts,
  type FilterKind,
} from "../../lib/useAssetFilter";
import { FRESHNESS_LABEL } from "../AssetMetaBadges";
import { Button, buttonClass } from "../ui/Button";
import { Popover } from "../ui/Popover";
import { SearchInput } from "../SearchInput";
import { matchesText } from "../../lib/text";

interface Props {
  active: readonly AssetFilter[];
  counts: FilterCounts;
  onToggle: (f: AssetFilter) => void;
  onClear: () => void;
  projects?: readonly ProjectSummary[];
  docTypeLabels?: ReadonlyMap<string, string>;
  /** Filter kinds this list offers (a project page has no project filter). */
  kinds?: readonly FilterKind[];
}

interface Option {
  value: AssetFilter;
  label: string;
}

interface Group {
  kind: FilterKind;
  title: MessageKey;
  options: Option[];
}

const FIXED: Partial<Record<FilterKind, ReadonlyArray<{ value: AssetFilter; label: MessageKey }>>> = {
  type: [
    { value: "type:md_single", label: "kind.mdSingle" },
    { value: "type:md_collection", label: "sidebarNav.collections" },
    { value: "type:html_bundle", label: "sidebarNav.bundles" },
    { value: "type:pdf_doc", label: "sidebarNav.pdfs" },
    { value: "type:office_doc", label: "sidebarNav.documents" },
  ],
  state: [
    { value: "state:public", label: "sidebarNav.public" },
    { value: "state:password", label: "sidebarNav.password" },
    { value: "state:unshared", label: "sidebarNav.unshared" },
  ],
  source: [
    { value: "source:gitlab", label: "sidebarNav.gitlab" },
    { value: "source:manual", label: "sidebarNav.manual" },
  ],
};

const TITLES: Record<FilterKind, MessageKey> = {
  type: "sidebarNav.types",
  state: "sidebarNav.state",
  source: "sidebarNav.source",
  project: "nav.projects",
  doctype: "sidebarNav.docTypes",
  fresh: "sidebarNav.freshness",
  tag: "sidebarNav.tags",
};

const ALL_KINDS: readonly FilterKind[] = ["type", "state", "source", "project", "doctype", "fresh", "tag"];

/** Filter groups with at least one option that would show something (or is on). */
function useGroups({ active, counts, projects, docTypeLabels, kinds = ALL_KINDS }: Props): Group[] {
  return useMemo(() => {
    const has = (v: AssetFilter) => (counts.get(v) ?? 0) > 0 || active.includes(v);
    const collator = new Intl.Collator(intlLocale());
    const dynamic = (kind: FilterKind, label: (value: string) => string): Option[] => {
      const out: Option[] = [];
      const seen = new Set<string>();
      for (const key of [...counts.keys(), ...active]) {
        if (filterKind(key) !== kind || seen.has(key)) continue;
        seen.add(key);
        out.push({ value: key, label: label(key.slice(kind.length + 1)) });
      }
      return out.sort((a, b) => collator.compare(a.label, b.label));
    };
    const projectName = new Map((projects ?? []).map((p) => [p.id, p.name]));
    const groups: Group[] = [];
    for (const kind of kinds) {
      let options: Option[];
      const fixed = FIXED[kind];
      if (fixed) options = fixed.map((o) => ({ value: o.value, label: t(o.label) }));
      else if (kind === "fresh")
        options = FRESHNESS_VALUES.map((v) => ({ value: `fresh:${v}` as AssetFilter, label: t(FRESHNESS_LABEL[v]) }));
      else if (kind === "project") options = dynamic("project", (id) => projectName.get(id) ?? t("assetToolbar.hiddenProject"));
      else if (kind === "doctype") options = dynamic("doctype", (k) => docTypeLabels?.get(k) ?? k);
      else options = dynamic("tag", (tag) => `#${tag}`);
      options = options.filter((o) => has(o.value));
      // A single option offers no choice, unless it is already on.
      if (options.length > 1 || options.some((o) => active.includes(o.value))) groups.push({ kind, title: TITLES[kind], options });
    }
    return groups;
  }, [active, counts, projects, docTypeLabels, kinds]);
}

/** Labels of the active filters, for the chips under the toolbar. */
function useActiveLabels(props: Props, groups: Group[]): Option[] {
  return props.active.map((value) => {
    for (const g of groups) {
      const hit = g.options.find((o) => o.value === value);
      if (hit) return hit;
    }
    return { value, label: value.slice(value.indexOf(":") + 1) };
  });
}

/**
 * "Filters" button of a document list toolbar and the chips of what is on.
 * Values of one group are alternatives, groups narrow each other; the count
 * next to a value says how many documents it would show right now.
 */
export function DocumentFilters(props: Props) {
  const { active, counts, onToggle, onClear } = props;
  const groups = useGroups(props);
  if (groups.length === 0 && active.length === 0) return null;

  return (
    <Popover
      label={t("filters.title")}
      widthClass="w-[22rem]"
      trigger={(p) => (
        <button
          type="button"
          {...p}
          className={clsx(buttonClass("secondary", "md"), active.length > 0 && "border-accent/50 text-accent")}
        >
          <ListFilter size={16} aria-hidden />
          {t("filters.title")}
          {active.length > 0 && (
            <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-accent px-1.5 text-caption font-semibold text-on-accent tabular-nums">
              {active.length}
            </span>
          )}
        </button>
      )}
      footer={({ close }) => (
        <div className="flex items-center justify-between gap-2">
          <Button variant="ghost" size="sm" onClick={onClear} disabled={active.length === 0}>
            {t("filters.clear")}
          </Button>
          <Button size="sm" onClick={close}>
            {t("filters.done")}
          </Button>
        </div>
      )}
    >
      {() => (
        <div className="space-y-4">
          {groups.map((g) => (
            <FilterGroup key={g.kind} group={g} active={active} counts={counts} onToggle={onToggle} />
          ))}
        </div>
      )}
    </Popover>
  );
}

/** A group this long gets a search field and shows its first options until asked. */
const SEARCH_FROM = 8;
const SHOWN = 6;
const SEARCH_LABEL: Partial<Record<FilterKind, MessageKey>> = {
  project: "filters.searchProject",
  tag: "filters.searchTag",
  doctype: "filters.searchDocType",
};

function FilterGroup({
  group: g,
  active,
  counts,
  onToggle,
}: {
  group: Group;
  active: readonly AssetFilter[];
  counts: FilterCounts;
  onToggle: (f: AssetFilter) => void;
}) {
  const [query, setQuery] = useState("");
  const [all, setAll] = useState(false);
  const long = g.options.length >= SEARCH_FROM;
  // What is on stays in view whatever is typed, so it can be turned off.
  const on = g.options.filter((o) => active.includes(o.value));
  const rest = g.options.filter((o) => !active.includes(o.value) && matchesText(o.label, query));
  const capped = long && !all && !query.trim();
  const shown = [...on, ...(capped ? rest.slice(0, Math.max(0, SHOWN - on.length)) : rest)];
  const hidden = on.length + rest.length - shown.length;
  const title = t(g.title);

  return (
    <fieldset>
      <legend className="mb-1 text-meta font-medium text-text-secondary">{title}</legend>
      {long && (
        <SearchInput
          value={query}
          onChange={setQuery}
          placeholder={t(SEARCH_LABEL[g.kind] ?? "filters.search")}
          ariaLabel={t(SEARCH_LABEL[g.kind] ?? "filters.search")}
          className="mb-1"
        />
      )}
      <div className="space-y-0.5">
        {shown.map((o) => (
          <label
            key={o.value}
            className="flex min-h-9 cursor-pointer items-center gap-2.5 rounded-control px-2 text-ui text-text-primary hover:bg-surface-hover"
          >
            <input
              type="checkbox"
              checked={active.includes(o.value)}
              onChange={() => onToggle(o.value)}
              className="size-4 shrink-0 accent-accent"
            />
            <span className="min-w-0 flex-1 truncate">{o.label}</span>
            <span className="text-meta tabular-nums text-text-secondary">{counts.get(o.value) ?? 0}</span>
          </label>
        ))}
        {long && query.trim() && rest.length === 0 && (
          <p className="px-2 py-1.5 text-meta text-text-secondary">{t("filters.noMatch")}</p>
        )}
      </div>
      {hidden > 0 && (
        <button type="button" onClick={() => setAll(true)} className="mt-1 px-2 text-ui font-medium text-accent hover:underline">
          {t("filters.showAll", { count: g.options.length })}
        </button>
      )}
    </fieldset>
  );
}

/** Removable chips of the active filters, with "clear all". */
export function ActiveFilterChips(props: Props) {
  const groups = useGroups(props);
  const labels = useActiveLabels(props, groups);
  if (labels.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5" aria-label={t("filters.active")} role="group">
      {labels.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => props.onToggle(o.value)}
          aria-label={t("filters.remove", { name: o.label })}
          className="inline-flex h-7 max-w-[16rem] items-center gap-1 rounded-full border border-accent/30 bg-accent-soft pl-2.5 pr-1.5 text-meta font-medium text-accent transition-colors duration-150 hover:border-accent/60"
        >
          <span className="truncate">{o.label}</span>
          <X size={14} aria-hidden className="shrink-0" />
        </button>
      ))}
      <button
        type="button"
        onClick={props.onClear}
        className="h-7 rounded-control px-2 text-meta font-medium text-text-secondary hover:bg-surface-hover hover:text-text-primary"
      >
        {t("filters.clear")}
      </button>
    </div>
  );
}
