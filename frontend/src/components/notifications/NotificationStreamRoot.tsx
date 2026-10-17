import { useCallback } from "react";
import type { NotificationItem } from "../../api/notificationTypes";
import { useUnreadCount } from "../../lib/notifications/queries";
import { useNotificationStream, useUnreadIndicators } from "../../lib/notifications/useNotificationStream";
import { useSessionUser } from "../../lib/useSessionUser";
import { useToast } from "../Toast";
import { notificationPlainText } from "./notificationText";

function LiveNotifications() {
  const { toast } = useToast();
  const onNew = useCallback(
    (item: NotificationItem) => {
      if (document.visibilityState === "visible") toast(notificationPlainText(item), "info");
    },
    [toast],
  );
  useNotificationStream(onNew);
  useUnreadIndicators(useUnreadCount());
  return null;
}

/**
 * The app's live notification stream, mounted once in `App` so page changes
 * and chrome remounts never close it. Runs once the session user is in
 * `qk.me()`.
 */
export function NotificationStreamRoot() {
  return useSessionUser(false) ? <LiveNotifications /> : null;
}
