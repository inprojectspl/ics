import { useCallback } from "react";
import { useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";

/**
 * Optimistic write of one cached value: the cache takes `optimistic` at once, the
 * server response replaces it, and a failure puts the previous value back
 * before `onError` reports it.
 */
export function useOptimisticUpdate<T>(queryKey: QueryKey, onError: (err: unknown) => void) {
  const qc = useQueryClient();
  return useCallback(
    async (optimistic: T, request: () => Promise<T>) => {
      await qc.cancelQueries({ queryKey });
      const previous = qc.getQueryData<T>(queryKey);
      qc.setQueryData<T>(queryKey, optimistic);
      try {
        qc.setQueryData<T>(queryKey, await request());
      } catch (err) {
        qc.setQueryData<T>(queryKey, previous);
        onError(err);
      }
    },
    [qc, queryKey, onError],
  );
}

/** A value only this user changes (a watch level): read once, never stale,
 * written optimistically through `write`. */
export function useOptimisticQuery<T>(
  queryKey: QueryKey,
  queryFn: () => Promise<T>,
  onError: (err: unknown) => void,
) {
  const { data } = useQuery({ queryKey, queryFn, retry: false, staleTime: Infinity });
  const write = useOptimisticUpdate<T>(queryKey, onError);
  return { data, write };
}
