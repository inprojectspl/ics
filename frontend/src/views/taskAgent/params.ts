import type { ContextInclude, ContextSystem } from "../../api";
import type { ContextPackQuery } from "../../api/relations";

// Limits of `GET /api/context` (backend `context_pack.py`).
export const MAX_DEPTH = 2;
export const MIN_BUDGET = 200;
export const MAX_BUDGET = 4000;
const DEFAULT_DEPTH = 1;
const DEFAULT_BUDGET = 1800;
export const INCLUDES: readonly ContextInclude[] = ["references", "deliverables"];

/** Form of the task agent view, kept in the query string so a link reproduces the pack. */
export interface TaskAgentParams {
  wp: string;
  system: ContextSystem;
  ancestors: string[];
  /** OP project identifier or ICS project slug; the project in view by default. */
  project: string;
  depth: number;
  budget: number;
  include: ContextInclude[];
}

function intIn(raw: string | null, min: number, max: number, fallback: number): number {
  if (raw === null || raw.trim() === "") return fallback;
  const n = Number(raw);
  return Number.isInteger(n) && n >= min && n <= max ? n : fallback;
}

/** `4700, 4650` and `4700 4650` alike, as the backend splits on commas. */
function splitList(raw: string | null): string[] {
  return (raw ?? "").split(/[\s,]+/).filter(Boolean);
}

function parseSystem(raw: string | null): ContextSystem {
  return raw === "project_standard" ? "project_standard" : "openproject";
}

function parseInclude(values: string[]): ContextInclude[] {
  const given = new Set(values.flatMap((v) => splitList(v)));
  return INCLUDES.filter((inc) => given.has(inc));
}

/** Params from a query string (`?wp=...`) or form data; garbage falls back to the defaults. */
export function readParams(source: URLSearchParams | FormData, slug: string): TaskAgentParams {
  const get = (key: string) => {
    const v = source.get(key);
    return typeof v === "string" ? v : null;
  };
  const all = (key: string) => source.getAll(key).filter((v): v is string => typeof v === "string");
  return {
    wp: (get("wp") ?? "").trim(),
    system: parseSystem(get("system")),
    ancestors: splitList(get("ancestors")),
    project: (get("project") ?? "").trim() || slug,
    depth: intIn(get("depth"), 0, MAX_DEPTH, DEFAULT_DEPTH),
    budget: intIn(get("budget"), MIN_BUDGET, MAX_BUDGET, DEFAULT_BUDGET),
    include: parseInclude(all("include")),
  };
}

/** Query string of the view (without `?`); defaults are left out to keep links short. */
export function toSearch(p: TaskAgentParams, slug: string): string {
  const q = new URLSearchParams();
  if (p.wp) q.set("wp", p.wp);
  if (p.system !== "openproject") q.set("system", p.system);
  if (p.ancestors.length) q.set("ancestors", p.ancestors.join(","));
  if (p.project !== slug) q.set("project", p.project);
  if (p.depth !== DEFAULT_DEPTH) q.set("depth", String(p.depth));
  if (p.budget !== DEFAULT_BUDGET) q.set("budget", String(p.budget));
  if (p.include.length) q.set("include", p.include.join(","));
  return q.toString();
}

/** The API request; every setting is sent explicitly, so the shown call is the whole truth. */
export function toQuery(p: TaskAgentParams): ContextPackQuery {
  return {
    wp: p.wp,
    system: p.system,
    ancestors: p.ancestors,
    project: p.project,
    depth: p.depth,
    budgetTokens: p.budget,
    include: p.include,
  };
}
