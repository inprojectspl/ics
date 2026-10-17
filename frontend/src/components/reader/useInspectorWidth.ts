import { useCallback, useState, useSyncExternalStore } from "react";

const KEY = "ics-reader-inspector-width";

/** The docked inspector never gets narrower than its original 320 px. */
export const INSPECTOR_MIN_WIDTH = 320;
const INSPECTOR_MAX_WIDTH = 760;
/** Share of the window the inspector may take, so the text keeps the page. */
const MAX_SHARE = 0.5;

function readStored(): number {
  try {
    const n = Number(localStorage.getItem(KEY));
    return Number.isFinite(n) && n > 0 ? n : INSPECTOR_MIN_WIDTH;
  } catch {
    return INSPECTOR_MIN_WIDTH;
  }
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener("resize", onChange);
  return () => window.removeEventListener("resize", onChange);
}

/** Widest the inspector may be in a window this wide. */
export function maxInspectorWidth(windowWidth: number): number {
  return Math.max(INSPECTOR_MIN_WIDTH, Math.min(INSPECTOR_MAX_WIDTH, Math.floor(windowWidth * MAX_SHARE)));
}

export function clampInspectorWidth(width: number, windowWidth: number): number {
  return Math.round(Math.min(maxInspectorWidth(windowWidth), Math.max(INSPECTOR_MIN_WIDTH, width)));
}

export interface InspectorWidth {
  width: number;
  min: number;
  max: number;
  /** Live update while dragging; `persist` also remembers it. */
  setWidth: (width: number, persist?: boolean) => void;
}

/**
 * Width of the docked reader inspector, chosen by dragging its edge and
 * remembered in `localStorage` for every document. The stored value is
 * clamped to the current window, so a width picked on a large screen
 * never pushes the text off a smaller one.
 */
export function useInspectorWidth(): InspectorWidth {
  const windowWidth = useSyncExternalStore(subscribe, () => window.innerWidth, () => 1440);
  const [chosen, setChosen] = useState(readStored);
  const setWidth = useCallback(
    (next: number, persist = false) => {
      const value = clampInspectorWidth(next, window.innerWidth);
      setChosen(value);
      if (!persist) return;
      try {
        localStorage.setItem(KEY, String(value));
      } catch {
        /* not remembered, still works */
      }
    },
    [],
  );
  return {
    width: clampInspectorWidth(chosen, windowWidth),
    min: INSPECTOR_MIN_WIDTH,
    max: maxInspectorWidth(windowWidth),
    setWidth,
  };
}
