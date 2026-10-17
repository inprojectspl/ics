// Fixtures for the notification tests.
import type { InfiniteData } from "@tanstack/react-query";
import type {
  NotificationItem,
  NotificationPage,
  NotificationPreferences,
} from "./api/notificationTypes";

let seq = 0;

export function mkItem(over: Partial<NotificationItem> = {}): NotificationItem {
  seq += 1;
  return {
    id: `1727520000000-${seq}`,
    code: "asset.updated",
    at: new Date().toISOString(),
    read: false,
    unavailable: false,
    actor: { id: "u2", name: "Alice Smith" },
    asset: { id: `a${seq}`, slug: `s${seq}`, title: "API spec", kind: "md_single" },
    project: { slug: "crm", name: "CRM" },
    version: 4,
    from_version: null,
    count: 1,
    link: `/v/s${seq}`,
    params: {},
    ...over,
  };
}

export function mkInbox(items: NotificationItem[], next: string | null = null) {
  const data: InfiniteData<NotificationPage, string | null> = {
    pages: [{ items, next }],
    pageParams: [null],
  };
  return data;
}

export function mkPrefs(over: Partial<NotificationPreferences> = {}): NotificationPreferences {
  return {
    enabled: true,
    watch_own_assets: true,
    email_mode: "off",
    events: {
      "asset.created": [],
      "asset.added": [],
      "asset.updated": ["push"],
      "asset.deleted": [],
    },
    chat: { configured: false, space: null, enabled: false, error_code: null },
    push: { available: true, public_key: "BAAA" },
    email_available: true,
    ...over,
  };
}
