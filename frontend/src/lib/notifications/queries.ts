import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { listNotifications, notificationSummary } from "../../api/notifications";
import type { NotificationFilter } from "../../api/notificationTypes";
import { qk } from "../queries";
import { useStreamLive } from "./liveState";

// While the stream is live it keeps both current (`apply.ts`) and a `reset`
// invalidates them, so they never go stale; without it (no EventSource, lost
// session) they refetch as usual.
const STALE_MS = 60_000;

function freshness(live: boolean) {
  return { staleTime: live ? Infinity : STALE_MS, refetchOnWindowFocus: !live };
}

export function useUnreadCount(): number | undefined {
  const live = useStreamLive();
  return useQuery({
    queryKey: qk.notificationSummary(),
    queryFn: notificationSummary,
    ...freshness(live),
    retry: false,
  }).data?.unread;
}

/** Inbox pages over the cursor; `next` of a page is `before` of the next. */
export function useInbox(filter: NotificationFilter, enabled = true) {
  const live = useStreamLive();
  return useInfiniteQuery({
    queryKey: qk.notificationList(filter),
    queryFn: ({ pageParam }) => listNotifications({ before: pageParam, filter }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next,
    ...freshness(live),
    enabled,
  });
}
