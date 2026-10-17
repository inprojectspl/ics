// Notifications, preferences, push devices and watches (docs/notifications-api.md).
import { postJson, putJson, req } from "./_core";
import type {
  AssetWatch,
  AssetWatchLevel,
  NotificationFilter,
  NotificationPage,
  NotificationPreferences,
  PreferencesPatch,
  ProjectWatch,
  ProjectWatchLevel,
  PushDevice,
  PushSubscriptionBody,
  UnreadCount,
  WatchList,
} from "./notificationTypes";

const NOTIFICATIONS_PAGE_SIZE = 30;
export const STREAM_URL = "/api/notifications/stream";

export function listNotifications(
  opts: { before?: string | null; limit?: number; filter?: NotificationFilter } = {},
): Promise<NotificationPage> {
  const q = new URLSearchParams();
  if (opts.before) q.set("before", opts.before);
  q.set("limit", String(opts.limit ?? NOTIFICATIONS_PAGE_SIZE));
  if (opts.filter === "unread") q.set("unread", "true");
  return req<NotificationPage>(`/api/notifications?${q.toString()}`);
}

export const notificationSummary = () => req<UnreadCount>("/api/notifications/summary");

/** `keepalive`: a row click marks the entry read and then leaves the page. */
export const markRead = (ids: string[]) =>
  postJson<UnreadCount>("/api/notifications/read", { ids }, { keepalive: true });

export const markAllRead = () => postJson<UnreadCount>("/api/notifications/read", { all: true });

export const markUnread = (ids: string[]) =>
  postJson<UnreadCount>("/api/notifications/unread", { ids });

export const deleteNotification = (id: string) =>
  req<UnreadCount>(`/api/notifications/${encodeURIComponent(id)}`, { method: "DELETE" });

export const clearNotifications = () => req<UnreadCount>("/api/notifications", { method: "DELETE" });

export const getPreferences = () =>
  req<NotificationPreferences>("/api/notifications/preferences");

export const updatePreferences = (patch: PreferencesPatch) =>
  putJson<NotificationPreferences>("/api/notifications/preferences", patch);

export const sendChatTest = () => postJson<void>("/api/notifications/chat/test", {});

export const listPushDevices = () =>
  req<{ items: PushDevice[] }>("/api/notifications/push/subscriptions");

export const savePushSubscription = (body: PushSubscriptionBody) =>
  putJson<{ id: string }>("/api/notifications/push/subscriptions", body);

export const unsubscribePush = (endpoint: string) =>
  postJson<void>("/api/notifications/push/unsubscribe", { endpoint });

export const deletePushDevice = (id: string) =>
  req<void>(`/api/notifications/push/subscriptions/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });

export const unsubscribeEmail = (token: string) =>
  postJson<void>("/api/notifications/unsubscribe", { token });

export const getAssetWatch = (assetId: string) => req<AssetWatch>(`/api/assets/${assetId}/watch`);

export const setAssetWatch = (assetId: string, level: AssetWatchLevel) =>
  putJson<AssetWatch>(`/api/assets/${assetId}/watch`, { level });

export const clearAssetWatch = (assetId: string) =>
  req<AssetWatch>(`/api/assets/${assetId}/watch`, { method: "DELETE" });

export const getProjectWatch = (slug: string) => req<ProjectWatch>(`/api/projects/${slug}/watch`);

export const setProjectWatch = (slug: string, level: ProjectWatchLevel) =>
  putJson<ProjectWatch>(`/api/projects/${slug}/watch`, { level });

export const clearProjectWatch = (slug: string) =>
  req<ProjectWatch>(`/api/projects/${slug}/watch`, { method: "DELETE" });

export const WATCHES_PAGE_SIZE = 25;

export const listWatches = (page: number) =>
  req<WatchList>(`/api/watches?page=${page}&page_size=${WATCHES_PAGE_SIZE}`);
