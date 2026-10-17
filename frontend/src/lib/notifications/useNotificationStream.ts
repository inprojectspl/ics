import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { NotificationItem } from "../../api/notificationTypes";
import { qk } from "../queries";
import { applyStreamEvent } from "./apply";
import { setStreamLive } from "./liveState";
import { openNotificationStream } from "./stream";
import { setAppBadge, setTitleCount } from "./titleBadge";

/** Message the service worker posts to a focused tab instead of showing an
 * OS notification; `src/sw.ts` repeats the string (it is built without imports). */
export const SW_PUSH_MESSAGE = "ics-push";

/**
 * Live notifications for a signed-in page: keeps the query cache current
 * from the shared stream and calls `onNew` for each new entry. Mounted once
 * per page, by the bell in the chrome.
 */
export function useNotificationStream(onNew?: (item: NotificationItem) => void): void {
  const qc = useQueryClient();
  const onNewRef = useRef(onNew);
  useEffect(() => {
    onNewRef.current = onNew;
  });

  useEffect(() => {
    const stream = openNotificationStream(
      (event) => applyStreamEvent(qc, event, (item) => onNewRef.current?.(item)),
      setStreamLive,
    );
    // A push handed to a focused tab is already in the cache when the stream
    // is up; only a tab without a live stream refreshes the badge.
    const sw = typeof navigator === "undefined" ? undefined : navigator.serviceWorker;
    const onMessage = (e: MessageEvent) => {
      const data: unknown = e.data;
      if (typeof data === "object" && data !== null && "type" in data && data.type === SW_PUSH_MESSAGE && !stream.live()) {
        void qc.invalidateQueries({ queryKey: qk.notificationSummary() });
      }
    };
    sw?.addEventListener("message", onMessage);
    return () => {
      stream.close();
      sw?.removeEventListener("message", onMessage);
    };
  }, [qc]);
}

/** Mirrors the unread count to the tab title and the app icon badge. */
export function useUnreadIndicators(unread: number | undefined): void {
  useEffect(() => {
    if (unread === undefined) return;
    setTitleCount(unread);
    setAppBadge(unread);
  }, [unread]);
  useEffect(() => () => setTitleCount(0), []);
}
