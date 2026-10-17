import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { qk } from "./queries";
import { useDebouncedValue } from "./useDebouncedValue";

export const canSearchDocuments = (q: string) => q.length >= 2 || /^[0-9]$/.test(q);

/** A result belongs to the current input, including during the debounce. */
export function useDocumentSearch(input: string, limit: number) {
  const q = input.trim();
  const debounced = useDebouncedValue(q, 250);
  const pending = q !== debounced;
  const enabled = canSearchDocuments(q);
  const query = useQuery({
    queryKey: qk.assetSearch(q, limit),
    queryFn: ({ signal }) => api.searchAssets(q, limit, undefined, signal),
    enabled: enabled && !pending,
    retry: false,
  });
  return {
    data: enabled && !pending ? query.data : undefined,
    error: enabled && !pending ? query.error : null,
    isSearching: enabled && (pending || query.isFetching),
  };
}
