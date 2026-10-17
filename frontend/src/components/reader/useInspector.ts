import { useCallback, useMemo, useState } from "react";
import { useMediaQuery } from "../../lib/useMediaQuery";
import type { InspectorState, InspectorTab } from "./ReaderLayout";

const KEY = "ics-reader-inspector";

/** Wide enough for the text and a docked 320 px inspector next to the sidebar. */
export const INSPECTOR_DOCKED = "(min-width: 1280px)";

type Kind = "collection" | "document";
type Remembered = Partial<Record<Kind, boolean>>;

function read(): Remembered {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) ?? "{}");
    return raw && typeof raw === "object" ? (raw as Remembered) : {};
  } catch {
    return {};
  }
}

/**
 * Open state and tab of the reader inspector, remembered per kind. Defaults
 * (closed, a collection on its file tree) apply only where it docks beside
 * the text; as a drawer it opens only when asked. Derived at render from
 * `kind`, so nothing flips after the first paint.
 */
export function useInspector(kind: Kind | null): InspectorState {
  const [openChoice, setOpenChoice] = useState<boolean | null>(null);
  const [tabChoice, setTabChoice] = useState<InspectorTab | null>(null);
  const docked = useMediaQuery(INSPECTOR_DOCKED);
  const collection = kind === "collection";
  // Read once per kind; after that the user's own choice (state) wins.
  const remembered = useMemo(() => (kind ? read()[kind] : undefined), [kind]);
  const open = openChoice ?? (docked && kind ? (remembered ?? collection) : false);
  const tab = tabChoice ?? (collection ? "files" : "outline");

  const setOpen = useCallback(
    (next: boolean) => {
      setOpenChoice(next);
      // Closing the drawer on a phone says nothing about the docked panel.
      if (!kind || !docked) return;
      try {
        localStorage.setItem(KEY, JSON.stringify({ ...read(), [kind]: next }));
      } catch {
        /* not remembered, still works */
      }
    },
    [kind, docked],
  );
  return { open, tab, docked, setOpen, setTab: setTabChoice };
}
