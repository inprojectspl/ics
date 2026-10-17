import { useSyncExternalStore } from "react";

/** Palette in effect on the page. */
export type Theme = "light" | "dark";
/** What the user picked; `system` follows the operating system. */
export type ThemePreference = Theme | "system";

const STORAGE_KEY = "ics-theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";

function systemTheme(): Theme {
  return window.matchMedia?.(DARK_QUERY).matches ? "dark" : "light";
}

export function readPreference(): ThemePreference {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "light" || saved === "dark" || saved === "system") return saved;
  } catch {
    /* storage blocked: fall back to the system */
  }
  return "system";
}

/** Palette the page renders with. The pre-paint script in index.html sets
 * `data-theme` before React starts, so this matches the first frame. */
export function getInitialTheme(): Theme {
  if (typeof document === "undefined") return "light";
  const attr = document.documentElement.getAttribute("data-theme");
  if (attr === "light" || attr === "dark") return attr;
  return systemTheme();
}

type Listener = () => void;
const listeners = new Set<Listener>();
let preference: ThemePreference = typeof window === "undefined" ? "system" : readPreference();
let resolved: Theme = typeof document === "undefined" ? "light" : getInitialTheme();

function emit() {
  for (const l of listeners) l();
}

function resolve(pref: ThemePreference): Theme {
  return pref === "system" ? systemTheme() : pref;
}

function commit(next: Theme) {
  document.documentElement.setAttribute("data-theme", next);
  if (next === resolved) return;
  resolved = next;
  emit();
}

/** Stores the preference and repaints the page with the palette it implies. */
export function setThemePreference(next: ThemePreference): void {
  try {
    localStorage.setItem(STORAGE_KEY, next);
  } catch {
    /* ignore */
  }
  const changed = next !== preference;
  preference = next;
  commit(resolve(next));
  if (changed) emit();
}

/** Kept for callers that force one palette (tests, graph snapshots). */
export function applyTheme(theme: Theme): void {
  setThemePreference(theme);
}

let mediaBound = false;
function bindSystemListener() {
  if (mediaBound || typeof window === "undefined" || !window.matchMedia) return;
  mediaBound = true;
  window.matchMedia(DARK_QUERY).addEventListener?.("change", () => {
    if (preference === "system") commit(systemTheme());
  });
}

function subscribe(listener: Listener): () => void {
  bindSystemListener();
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Palette in effect, shared by every component (markdown, mermaid, PDF). */
export function useTheme(): Theme {
  return useSyncExternalStore(
    subscribe,
    () => resolved,
    () => "light",
  );
}

/** The stored choice, for the settings control in the account menu. */
export function useThemePreference(): [ThemePreference, (next: ThemePreference) => void] {
  const pref = useSyncExternalStore(
    subscribe,
    () => preference,
    () => "system" as ThemePreference,
  );
  return [pref, setThemePreference];
}
