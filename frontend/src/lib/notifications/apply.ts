// Live events and local mutations applied to the TanStack Query cache:
// `setQueryData` on the summary and the loaded list pages, no refetch.
import type { QueryClient } from "@tanstack/react-query";
import type {
  NotificationFilter,
  NotificationItem,
  NotificationStreamEvent,
  NotificationSyncData,
} from "../../api/notificationTypes";
import { qk } from "../queries";
import { withNotification, withSync, type Inbox } from "./cache";

const FILTERS: readonly NotificationFilter[] = ["all", "unread"];

export function applySync(qc: QueryClient, sync: NotificationSyncData): void {
  qc.setQueryData(qk.notificationSummary(), { unread: sync.unread });
  for (const filter of FILTERS) {
    qc.setQueryData<Inbox>(qk.notificationList(filter), (d) => withSync(d, sync));
  }
}

export function applyStreamEvent(
  qc: QueryClient,
  event: NotificationStreamEvent,
  onNew?: (item: NotificationItem) => void,
): void {
  switch (event.type) {
    case "notification": {
      const { item, unread } = event.data;
      qc.setQueryData(qk.notificationSummary(), { unread });
      for (const filter of FILTERS) {
        qc.setQueryData<Inbox>(qk.notificationList(filter), (d) =>
          withNotification(d, item, filter),
        );
      }
      onNew?.(item);
      return;
    }
    case "sync":
      applySync(qc, event.data);
      return;
    case "reset":
      void qc.invalidateQueries({ queryKey: qk.notifications() });
      return;
  }
}
