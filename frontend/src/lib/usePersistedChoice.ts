import { useCallback, useState } from "react";

/**
 * A choice between a few string options, remembered in `localStorage` under
 * `key`. A stored value outside `options` (an old build, manual edits) reads
 * as `fallback`. Blocked storage (private window) only means the choice does
 * not survive a reload.
 */
export function usePersistedChoice<T extends string>(
  key: string,
  options: readonly T[],
  fallback: T,
): [T, (next: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const stored = window.localStorage.getItem(key);
      return options.find((o) => o === stored) ?? fallback;
    } catch {
      return fallback;
    }
  });
  const choose = useCallback(
    (next: T) => {
      setValue(next);
      try {
        window.localStorage.setItem(key, next);
      } catch {
        // See above: the choice just won't survive a reload.
      }
    },
    [key],
  );
  return [value, choose];
}
