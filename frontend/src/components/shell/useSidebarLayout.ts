import { useCallback, useState } from "react";
import { usePersistedChoice } from "../../lib/usePersistedChoice";
import { useMediaQuery } from "../../lib/useMediaQuery";

/** Width classes of the shell (DESIGN.md 2.2 and 12). */
const DESKTOP_QUERY = "(min-width: 1024px)";
const TABLET_QUERY = "(min-width: 768px)";

type SidebarMode = "expanded" | "rail" | "hidden";

export interface SidebarLayout {
  /** What the persistent column shows right now. */
  mode: SidebarMode;
  /** Wide enough for the persistent column to follow the user's preference. */
  desktop: boolean;
  /** The desktop preference, remembered across pages and reloads. */
  collapsed: boolean;
  toggleCollapsed: () => void;
  /** Full navigation as an overlay: the drawer on phones, the expanded
   * panel over the rail on tablets. */
  drawerOpen: boolean;
  openDrawer: () => void;
  closeDrawer: () => void;
}

/**
 * Desktop (1024+): expanded 256 px or the 64 px rail, by preference.
 * Tablet (768-1023): the rail; the full tree opens over the content.
 * Phone: no column, the tree is a drawer.
 */
export function useSidebarLayout(focusMode: boolean): SidebarLayout {
  const desktop = useMediaQuery(DESKTOP_QUERY);
  const tablet = useMediaQuery(TABLET_QUERY);
  const [pref, setPref] = usePersistedChoice("ics-sidebar", ["expanded", "collapsed"] as const, "expanded");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const collapsed = pref === "collapsed";

  const toggleCollapsed = useCallback(
    () => setPref(collapsed ? "expanded" : "collapsed"),
    [collapsed, setPref],
  );
  const openDrawer = useCallback(() => setDrawerOpen(true), []);
  const closeDrawer = useCallback(() => setDrawerOpen(false), []);

  let mode: SidebarMode;
  if (focusMode || !tablet) mode = "hidden";
  else if (!desktop) mode = "rail";
  else mode = collapsed ? "rail" : "expanded";

  return { mode, desktop, collapsed, toggleCollapsed, drawerOpen, openDrawer, closeDrawer };
}
