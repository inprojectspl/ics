import { useMemo } from "react";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import {
  clearNotifications,
  deleteNotification,
  markAllRead,
  markRead,
  markUnread,
} from "../../api/notifications";
import type { NotificationItem, UnreadCount } from "../../api/notificationTypes";
import { qk } from "../queries";
import { applySync } from "./apply";

export interface InboxActions {
  /** Row opened: marks it read (the request survives leaving the page). */
  markOpened: (item: NotificationItem) => void;
  toggleRead: (item: NotificationItem) => void;
  remove: (item: NotificationItem) => void;
  markAllRead: () => void;
  clearAll: () => void;
}

function unreadNow(qc: QueryClient): number {
  return qc.getQueryData<UnreadCount>(qk.notificationSummary())?.unread ?? 0;
}

/**
 * Inbox mutations, applied to the cache first and confirmed by the server's
 * unread count. A failure refetches the inbox, which rolls the optimistic
 * change back, and reports the error.
 */
export function useInboxActions(onError: (err: unknown) => void): InboxActions {
  const qc = useQueryClient();
  return useMemo(() => {
    const settle = (request: Promise<UnreadCount>) =>
      request.then(
        ({ unread }) => applySync(qc, { unread }),
        (err: unknown) => {
          void qc.invalidateQueries({ queryKey: qk.notifications() });
          onError(err);
        },
      );
    const read = (item: NotificationItem) => {
      applySync(qc, { unread: Math.max(0, unreadNow(qc) - 1), read: [item.id] });
      void settle(markRead([item.id]));
    };
    return {
      markOpened: (item) => {
        if (!item.read) read(item);
      },
      toggleRead: (item) => {
        if (!item.read) {
          read(item);
          return;
        }
        applySync(qc, { unread: unreadNow(qc) + 1, unread_ids: [item.id] });
        void settle(markUnread([item.id]));
      },
      remove: (item) => {
        const unread = unreadNow(qc) - (item.read ? 0 : 1);
        applySync(qc, { unread: Math.max(0, unread), deleted: [item.id] });
        void settle(deleteNotification(item.id));
      },
      markAllRead: () => {
        applySync(qc, { unread: 0, all_read: true });
        void settle(markAllRead());
      },
      clearAll: () => {
        applySync(qc, { unread: 0, cleared: true });
        void settle(clearNotifications());
      },
    };
  }, [qc, onError]);
}
