import { useCallback, useEffect, useMemo, useState } from "react";
import { AssetSummary, Freshness } from "../api";
import { replaceUrl } from "./navigate";

/**
 * Which documents a view shows. Chosen in the sidebar (Documents -> All,
 * Mine, Shared with me, Favourites); an administrator also has the review
 * queue. One scope at a time.
 */
export type AssetScope = "all" | "state:pinned" | "state:mine" | "state:shared-with-me" | "admin:review";

const SCOPES: readonly AssetScope[] = [
  "all",
  "state:pinned",
  "state:mine",
  "state:shared-with-me",
  "admin:review",
];

/**
 * Filters over the scope, chosen in the toolbar popover. Values of one kind
 * are alternatives (OR: Markdown or PDF), different kinds narrow further
 * (AND: PDF and public). The values are URL-safe and stable, so links keep
 * working when the labels change.
 */
export type AssetFilter =
  | `type:${"md_single" | "md_collection" | "html_bundle" | "pdf_doc" | "office_doc"}`
  | `state:${"public" | "password" | "unshared"}`
  | `source:${"gitlab" | "manual"}`
  | `project:${string}`
  | `doctype:${string}`
  | `fresh:${Freshness}`
  | `tag:${string}`;

export type FilterKind = "type" | "state" | "source" | "project" | "doctype" | "fresh" | "tag";

const FILTER_KINDS: readonly FilterKind[] = ["type", "state", "source", "project", "doctype", "fresh", "tag"];

export const FRESHNESS_VALUES: readonly Freshness[] = ["current", "review_overdue", "superseded"];

const URL_PARAM = "f";

function isScope(v: string): v is AssetScope {
  return (SCOPES as readonly string[]).includes(v);
}

export function filterKind(f: AssetFilter): FilterKind {
  return f.slice(0, f.indexOf(":")) as FilterKind;
}

function isFilter(v: string): v is AssetFilter {
  const colon = v.indexOf(":");
  return colon > 0 && colon < v.length - 1 && (FILTER_KINDS as readonly string[]).includes(v.slice(0, colon));
}

interface FilterState {
  scope: AssetScope;
  filters: readonly AssetFilter[];
}

const EMPTY: FilterState = { scope: "all", filters: [] };

function readFromUrl(): FilterState {
  let scope: AssetScope = "all";
  const filters: AssetFilter[] = [];
  for (const v of new URLSearchParams(window.location.search).getAll(URL_PARAM)) {
    if (isScope(v)) {
      if (scope === "all") scope = v;
    } else if (isFilter(v) && !filters.includes(v)) filters.push(v);
  }
  return { scope, filters };
}

function writeToUrl({ scope, filters }: FilterState) {
  const params = new URLSearchParams(window.location.search);
  params.delete(URL_PARAM);
  if (scope !== "all") params.append(URL_PARAM, scope);
  for (const f of filters) params.append(URL_PARAM, f);
  const qs = params.toString();
  replaceUrl(`${window.location.pathname}${qs ? "?" + qs : ""}${window.location.hash}`);
}

/** Link to the document list in `scope` (the sidebar entries). */
export function scopeHref(scope: AssetScope): string {
  return scope === "all" ? "/" : `/?${URL_PARAM}=${encodeURIComponent(scope)}`;
}

function inScope(a: AssetSummary, scope: AssetScope): boolean {
  switch (scope) {
    case "all":
      return true;
    case "state:mine":
      return a.access_source === "owned" || a.access_source === undefined;
    case "state:shared-with-me":
      return a.access_source === "direct" || a.access_source === "project";
    case "state:pinned":
      return Boolean(a.pinned_at);
    case "admin:review":
      return a.security_status === "critical" && !a.security_bypass;
  }
}

/** Filter values an asset carries, one list per kind. */
function valuesOf(a: AssetSummary, kind: FilterKind): readonly string[] {
  switch (kind) {
    case "type":
      return [a.kind];
    case "state": {
      const modes = a.active_share_modes ?? [];
      if (modes.length === 0) return ["unshared"];
      return modes.filter((m) => m === "public" || m === "password");
    }
    case "source":
      return [a.has_binding ? "gitlab" : "manual"];
    case "project":
      return a.project_id ? [a.project_id] : [];
    case "doctype":
      return a.doc_type ? [a.doc_type] : [];
    case "fresh":
      return a.freshness ? [a.freshness] : [];
    case "tag":
      return a.tags ?? [];
  }
}

type Groups = ReadonlyArray<readonly [FilterKind, readonly string[]]>;

function group(filters: readonly AssetFilter[]): Groups {
  const out: [FilterKind, string[]][] = [];
  for (const kind of FILTER_KINDS) {
    const prefix = `${kind}:`;
    const wanted = filters.filter((f) => f.startsWith(prefix)).map((f) => f.slice(prefix.length));
    if (wanted.length > 0) out.push([kind, wanted]);
  }
  return out;
}

function matches(a: AssetSummary, groups: Groups, skip?: FilterKind): boolean {
  for (const [kind, wanted] of groups) {
    if (kind === skip) continue;
    const have = valuesOf(a, kind);
    if (!wanted.some((w) => have.includes(w))) return false;
  }
  return true;
}

export type FilterCounts = ReadonlyMap<AssetFilter, number>;

/**
 * Pure hook over a list the caller owns: the scope and filters (synced to
 * `?f=`), the documents that pass, and counts for the filter menu. A
 * filter's count is how many documents it would show next to the other
 * active kinds, so picking it never leads to an empty list by surprise.
 */
export function useAssetFilterState() {
  const [state, setState] = useState<FilterState>(() =>
    typeof window === "undefined" ? EMPTY : readFromUrl(),
  );

  const update = useCallback((next: (prev: FilterState) => FilterState) => {
    setState((prev) => {
      const updated = next(prev);
      writeToUrl(updated);
      return updated;
    });
  }, []);

  const toggleFilter = useCallback(
    (f: AssetFilter) =>
      update((prev) => ({
        scope: prev.scope,
        filters: prev.filters.includes(f) ? prev.filters.filter((x) => x !== f) : [...prev.filters, f],
      })),
    [update],
  );
  const clearFilters = useCallback(() => update((prev) => ({ scope: prev.scope, filters: [] })), [update]);

  useEffect(() => {
    const onPop = () => setState(readFromUrl());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  return { ...state, toggleFilter, clearFilters };
}

export function useAssetFilter(assets: AssetSummary[], titleQuery: string) {
  const { scope, filters, toggleFilter, clearFilters } = useAssetFilterState();

  const scoped = useMemo(() => assets.filter((a) => inScope(a, scope)), [assets, scope]);

  const scopeCounts = useMemo(() => {
    const c = Object.fromEntries(SCOPES.map((s) => [s, 0])) as Record<AssetScope, number>;
    for (const a of assets) for (const s of SCOPES) if (inScope(a, s)) c[s] += 1;
    return c;
  }, [assets]);

  const counts: FilterCounts = useMemo(() => {
    const groups = group(filters);
    const c = new Map<AssetFilter, number>();
    for (const a of scoped) {
      for (const kind of FILTER_KINDS) {
        if (!matches(a, groups, kind)) continue;
        for (const v of valuesOf(a, kind)) {
          const key = `${kind}:${v}` as AssetFilter;
          c.set(key, (c.get(key) ?? 0) + 1);
        }
      }
    }
    return c;
  }, [scoped, filters]);

  const visible = useMemo(() => {
    const q = titleQuery.trim().toLowerCase();
    const groups = group(filters);
    return scoped.filter((a) => {
      if (!matches(a, groups)) return false;
      if (!q) return true;
      return (a.title ?? a.slug).toLowerCase().includes(q);
    });
  }, [scoped, filters, titleQuery]);

  return { scope, filters, toggleFilter, clearFilters, scopeCounts, counts, visible };
}
