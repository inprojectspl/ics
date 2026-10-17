import { useCallback } from "react";
import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { api, type RelationItem, type RelationList } from "../../api";
import { ApiError } from "../../api/_core";
import { qk } from "../../lib/queries";

/** No graph access is a 404; the relations UI then does not exist for this viewer. */
export function isHidden(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

/** The relation list, shared by the panel and the reader entry (one request, one cache entry). */
export function useRelations(slug: string) {
  return useQuery({
    queryKey: qk.relations(slug),
    queryFn: () => api.listRelations(slug),
    retry: (count, err) => !isHidden(err) && count < 2,
  });
}

/** Refetches the relation list and the neighbourhood graph, which draws the same edges. */
export async function invalidateRelations(queryClient: QueryClient, slug: string): Promise<void> {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: qk.relations(slug) }),
    queryClient.invalidateQueries({ queryKey: qk.neighbourhood(slug) }),
  ]);
}

function replaceItem(list: RelationList, id: string, patch: Partial<RelationItem>): RelationList {
  const update = (groups: RelationList["outgoing"]) =>
    Object.fromEntries(
      Object.entries(groups).map(([k, items]) => [
        k,
        (items ?? []).map((i) => (i.id === id ? { ...i, ...patch } : i)),
      ]),
    );
  return { ...list, outgoing: update(list.outgoing), incoming: update(list.incoming) };
}

/**
 * "Still current" on a changed basis: refreshes the pinned target version and
 * clears the flag in the cached relation list, shared by the relations panel
 * and the hygiene view. Throws the API error to the caller.
 */
export function useConfirmBasis(slug: string): (relationId: string) => Promise<void> {
  const queryClient = useQueryClient();
  return useCallback(
    async (relationId: string) => {
      await api.patchRelation(relationId, { refresh_target_version: true });
      const key = qk.relations(slug);
      const current = queryClient.getQueryData<RelationList>(key);
      if (current) queryClient.setQueryData(key, replaceItem(current, relationId, { target_changed: false }));
      else await queryClient.invalidateQueries({ queryKey: key });
      await queryClient.invalidateQueries({ queryKey: qk.neighbourhood(slug) });
    },
    [queryClient, slug],
  );
}
