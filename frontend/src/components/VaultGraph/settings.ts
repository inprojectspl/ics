import type { GraphSettings } from "./types";

export const DEFAULT_SETTINGS: GraphSettings = {
  repulsion: 1800,
  linkDistance: 300,
  linkForce: 0.02,
  nodeScale: 1.0,
  centerForce: 0.002,
  labels: "hover",
  showArrows: false,
};

const STORAGE_KEY = "ics:graph-settings";

export function loadSettings(): GraphSettings {
  if (typeof window === "undefined") return DEFAULT_SETTINGS;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_SETTINGS;
    const parsed = JSON.parse(raw);
    // Tolerant merge - added fields fall through to defaults; removed
    // fields are silently ignored. Keeps old saved configs forward-compatible.
    return { ...DEFAULT_SETTINGS, ...parsed };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

export function saveSettings(s: GraphSettings): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
  } catch {
    // private-mode browsers throw - silently ignore.
  }
}
