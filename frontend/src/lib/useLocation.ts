import { useSyncExternalStore } from "react";
import { LOCATION_EVENT } from "./navigate";

function subscribe(onChange: () => void): () => void {
  window.addEventListener("popstate", onChange);
  window.addEventListener(LOCATION_EVENT, onChange);
  return () => {
    window.removeEventListener("popstate", onChange);
    window.removeEventListener(LOCATION_EVENT, onChange);
  };
}

const snapshot = () => window.location.pathname + window.location.search;

/** Current path and query, for components that highlight where the user is. */
export function useLocation(): { pathname: string; search: URLSearchParams } {
  const href = useSyncExternalStore(subscribe, snapshot, () => "/");
  const q = href.indexOf("?");
  return {
    pathname: q === -1 ? href : href.slice(0, q),
    search: new URLSearchParams(q === -1 ? "" : href.slice(q + 1)),
  };
}
