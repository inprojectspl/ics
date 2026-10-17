import { useCallback, useState } from "react";

type PageUpdate = number | ((page: number) => number);

/**
 * Page number that falls back to 1 whenever `resetKey` changes. Stored with
 * the key it was chosen for and derived during render, so no reset effect
 * (and no extra render or request) is needed.
 */
export function useResettablePage(resetKey: string): [number, (next: PageUpdate) => void] {
  const [stored, setStored] = useState({ key: resetKey, page: 1 });
  const page = stored.key === resetKey ? stored.page : 1;
  const setPage = useCallback(
    (next: PageUpdate) =>
      setStored((prev) => {
        const current = prev.key === resetKey ? prev.page : 1;
        return { key: resetKey, page: typeof next === "function" ? next(current) : next };
      }),
    [resetKey],
  );
  return [page, setPage];
}
