// Notifications API contract (docs/notifications-api.md, ADR-0023).
import type { AssetKind } from "./types";

export type NotificationCode =
  | "asset.created"
  | "asset.added"
  | "asset.updated"
  | "asset.deleted"
  | "channel.chat_disabled";

export type EventKind = "asset.created" | "asset.added" | "asset.updated" | "asset.deleted";
/** Channels the user picks per event; in-app is always on and not listed. */
export type OptionalChannel = "push" | "email" | "chat";
export type EmailMode = "off" | "batched" | "daily";

interface NotificationAssetRef {
  id: string;
  slug: string;
  title: string;
  kind: AssetKind;
}

interface NotificationProjectRef {
  slug: string;
  name: string;
}

export interface NotificationItem {
  /** Opaque cursor, also the SSE event id. */
  id: string;
  code: NotificationCode;
  at: string;
  read: boolean;
  /** The recipient lost access: asset, project and link are null. */
  unavailable: boolean;
  /** Null for a system actor (CI sync). */
  actor: { id: string; name: string } | null;
  asset: NotificationAssetRef | null;
  project: NotificationProjectRef | null;
  version: number | null;
  from_version: number | null;
  /** Collapsed events, at least 1. */
  count: number;
  link: string | null;
  params: Record<string, string | number>;
}

export interface NotificationPage {
  items: NotificationItem[];
  next: string | null;
}

export interface UnreadCount {
  unread: number;
}

export type NotificationFilter = "all" | "unread";

interface NotificationEventData {
  item: NotificationItem;
  unread: number;
}

export interface NotificationSyncData {
  unread: number;
  read?: string[];
  unread_ids?: string[];
  deleted?: string[];
  all_read?: boolean;
  cleared?: boolean;
}

/** One live event, as the stream delivers it and tabs relay it. */
export type NotificationStreamEvent =
  | { type: "notification"; data: NotificationEventData }
  | { type: "sync"; data: NotificationSyncData }
  | { type: "reset" };

interface ChatSettings {
  configured: boolean;
  space: string | null;
  enabled: boolean;
  error_code: string | null;
}

export interface NotificationPreferences {
  enabled: boolean;
  watch_own_assets: boolean;
  email_mode: EmailMode;
  events: Record<EventKind, OptionalChannel[]>;
  chat: ChatSettings;
  /** VAPID public key, base64url. */
  push: { available: boolean; public_key: string | null };
  email_available: boolean;
}

export interface PreferencesPatch {
  enabled?: boolean;
  watch_own_assets?: boolean;
  email_mode?: EmailMode;
  events?: Partial<Record<EventKind, OptionalChannel[]>>;
  /** `null` removes the webhook. */
  chat_webhook_url?: string | null;
  chat_enabled?: boolean;
}

export interface PushDevice {
  id: string;
  label: string;
  created_at: string;
  last_success_at: string | null;
}

export interface PushSubscriptionBody {
  endpoint: string;
  keys: { p256dh: string; auth: string };
  label?: string;
}

export type AssetWatchLevel = "watch" | "mute";
export type ProjectWatchLevel = "new" | "all";

export interface AssetWatch {
  level: AssetWatchLevel | null;
  /** The asset's project is watched at this level. */
  via_project: ProjectWatchLevel | null;
  /** Owner or maintainer with `watch_own_assets` on. */
  own: boolean;
}

export interface ProjectWatch {
  level: ProjectWatchLevel | null;
}

/** The backend sends only the key of the watched kind. */
export type WatchItem =
  | { type: "asset"; level: AssetWatchLevel; created_at: string; asset: NotificationAssetRef }
  | { type: "project"; level: ProjectWatchLevel; created_at: string; project: NotificationProjectRef };

export interface WatchList {
  items: WatchItem[];
  total: number;
}
