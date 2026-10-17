import { useCallback, useSyncExternalStore } from "react";

/** Below Tailwind's `sm`: the phone layout (bottom sheets, bell as a link). */
export const MOBILE_QUERY = "(max-width: 639px)";

// One MediaQueryList per query for the whole app: every row menu asks for
// the phone query, and `matchMedia` builds a new object on each call.
const lists = new Map<string, MediaQueryList>();

function mediaList(query: string): MediaQueryList | undefined {
  if (!window.matchMedia) return undefined;
  let list = lists.get(query);
  if (!list) {
    list = window.matchMedia(query);
    lists.set(query, list);
  }
  return list;
}

/** Forgets the cached lists; for tests that stub `matchMedia` with a new viewport. */
export function resetMediaQueryCache(): void {
  lists.clear();
}

/** Live `matchMedia` result; `false` where the API is missing. */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const mql = mediaList(query);
      mql?.addEventListener?.("change", onChange);
      return () => mql?.removeEventListener?.("change", onChange);
    },
    [query],
  );
  return useSyncExternalStore(subscribe, () => Boolean(mediaList(query)?.matches), () => false);
}
