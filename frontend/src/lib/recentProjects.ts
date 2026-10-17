import { useSyncExternalStore } from "react";

const KEY = "ics-recent-projects";
const LIMIT = 5;
const listeners = new Set<() => void>();

function read(): string[] {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) ?? "[]");
    return Array.isArray(raw) ? raw.filter((s): s is string => typeof s === "string").slice(0, LIMIT) : [];
  } catch {
    return [];
  }
}

let cache = typeof window === "undefined" ? [] : read();

/** Moves the project to the front of the "recently opened" list the sidebar shows. */
export function rememberProject(slug: string): void {
  const next = [slug, ...cache.filter((s) => s !== slug)].slice(0, LIMIT);
  if (next.join() === cache.join()) return;
  cache = next;
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* the list just won't survive a reload */
  }
  for (const l of listeners) l();
}

function subscribe(l: () => void): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}

/** Slugs of the projects this browser opened last, newest first. */
export function useRecentProjects(): readonly string[] {
  return useSyncExternalStore(subscribe, () => cache, () => cache);
}
