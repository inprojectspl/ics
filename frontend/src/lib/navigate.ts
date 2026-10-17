/**
 * SPA navigation helper. Pushes a new history entry and synthesizes
 * a `popstate` event so the app's router picks it up. Use it instead of
 * inlining `window.history.pushState + dispatchEvent`.
 */
export function navigate(path: string): void {
  const before = window.location.pathname;
  window.history.pushState({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
  // A new page starts at the top; a new view of the same page (a sidebar
  // scope on the document list) keeps the reader where they are.
  if (window.location.pathname !== before) window.scrollTo({ top: 0 });
}

/** Rewrites the current address without a history entry (a filter change)
 * and tells location subscribers (`useLocation`) about it. */
export function replaceUrl(path: string): void {
  window.history.replaceState({}, "", path);
  window.dispatchEvent(new Event(LOCATION_EVENT));
}

/** Fired after `replaceUrl`; `popstate` covers everything else. */
export const LOCATION_EVENT = "ics:location";

/** A plain left click, which the SPA handles itself; modifier and middle
 * clicks are left to the browser (new tab, new window). */
export function isPlainClick(e: {
  button: number;
  metaKey: boolean;
  ctrlKey: boolean;
  shiftKey: boolean;
  altKey: boolean;
}): boolean {
  return e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey;
}
