import { useId, useMemo, useState } from "react";
import { clsx } from "clsx";
import type { ProjectSummary } from "../../api";
import { nameCollator, t } from "../../lib/i18n";
import { matchesText } from "../../lib/text";
import { SearchInput } from "../SearchInput";
import { ProjectMonogram } from "./ProjectMonogram";
import { ProjectRoleBadge } from "./ProjectRoleBadge";

/** From this many choices the list gets a search field. */
const SEARCH_FROM = 6;

interface Props {
  projects: readonly ProjectSummary[];
  /** Picked project id; "" is `noneLabel`. */
  value: string;
  onChange: (id: string) => void;
  /** Accessible name of the choice. */
  label: string;
  /** Offers "no project" as the first choice. */
  noneLabel?: string;
  disabled?: boolean;
}

/**
 * One project out of many: a search field (from a handful of projects on)
 * over a list of radio rows with the caller's role. Replaces a native
 * select, which cannot be searched and turns unusable at dozens of projects.
 */
export function ProjectPicker({ projects, value, onChange, label, noneLabel, disabled }: Props) {
  const [query, setQuery] = useState("");
  const name = useId();
  const sorted = useMemo(() => {
    const byName = nameCollator();
    return [...projects].sort((a, b) => byName.compare(a.name, b.name));
  }, [projects]);
  // The picked project stays listed whatever is typed.
  const shown = sorted.filter((p) => p.id === value || matchesText(p.name, query));
  const searching = query.trim() !== "";

  return (
    <div>
      {projects.length >= SEARCH_FROM && (
        <SearchInput value={query} onChange={setQuery} placeholder={t("filters.searchProject")} ariaLabel={t("filters.searchProject")} className="mb-2" />
      )}
      <div
        role="radiogroup"
        aria-label={label}
        className="max-h-72 overflow-y-auto overscroll-contain rounded-card border border-border bg-surface"
      >
        {noneLabel && !searching && (
          <Option name={name} checked={value === ""} disabled={disabled} onPick={() => onChange("")}>
            <span className="text-ui text-text-secondary">{noneLabel}</span>
          </Option>
        )}
        {shown.map((p) => (
          <Option key={p.id} name={name} checked={value === p.id} disabled={disabled} onPick={() => onChange(p.id)}>
            <ProjectMonogram name={p.name} />
            <span className="min-w-0 flex-1 truncate text-ui text-text-primary">{p.name}</span>
            <ProjectRoleBadge role={p.my_role} />
          </Option>
        ))}
        {searching && shown.length === 0 && <p className="px-3 py-3 text-ui text-text-secondary">{t("filters.noMatch")}</p>}
      </div>
    </div>
  );
}

function Option({
  name,
  checked,
  disabled,
  onPick,
  children,
}: {
  name: string;
  checked: boolean;
  disabled?: boolean;
  onPick: () => void;
  children: React.ReactNode;
}) {
  return (
    <label
      className={clsx(
        "flex min-h-11 cursor-pointer items-center gap-3 border-b border-border px-3 py-2 last:border-b-0 hover:bg-surface-hover",
        checked && "bg-accent-soft hover:bg-accent-soft",
        disabled && "cursor-not-allowed opacity-60",
      )}
    >
      <input type="radio" name={name} checked={checked} disabled={disabled} onChange={onPick} className="size-4 shrink-0 accent-accent" />
      {children}
    </label>
  );
}
