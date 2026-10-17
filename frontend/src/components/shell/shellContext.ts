import { createContext, useContext } from "react";

export interface ShellApi {
  /** Element the page's `PageContext` portals its breadcrumb bar into. */
  contextSlot: HTMLElement | null;
  /** Reading focus: the sidebar steps aside until the reader leaves it. */
  focusMode: boolean;
  setFocusMode: (on: boolean) => void;
  /** Path of the sidebar entry to mark active when the URL alone cannot
   * tell (a document inside a project marks that project). */
  setActiveHref: (href: string | null) => void;
  /** True inside the signed-in shell; false on public pages. */
  signedIn: boolean;
}

const NOOP_API: ShellApi = {
  contextSlot: null,
  focusMode: false,
  setFocusMode: () => {},
  setActiveHref: () => {},
  signedIn: false,
};

export const ShellContext = createContext<ShellApi>(NOOP_API);

export function useShell(): ShellApi {
  return useContext(ShellContext);
}
