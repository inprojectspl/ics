// Pure helpers of the notification settings screen.
import type {
  OptionalChannel,
  EventKind,
  NotificationPreferences,
  PreferencesPatch,
} from "../../api/notificationTypes";
import type { MessageKey } from "../i18n";

export const EVENT_KINDS: readonly EventKind[] = [
  "asset.created",
  "asset.added",
  "asset.updated",
  "asset.deleted",
];
/** The per-event channels; in-app is always on and has no setting. */
export const CHANNELS: readonly OptionalChannel[] = ["push", "email", "chat"];

export const EVENT_LABEL: Record<EventKind, MessageKey> = {
  "asset.created": "accountNotifications.event.created",
  "asset.added": "accountNotifications.event.added",
  "asset.updated": "accountNotifications.event.updated",
  "asset.deleted": "accountNotifications.event.deleted",
};

export const CHANNEL_LABEL: Record<OptionalChannel, MessageKey> = {
  push: "accountNotifications.channel.push",
  email: "accountNotifications.channel.email",
  chat: "accountNotifications.channel.chat",
};

/** The preferences as the server will return them after `patch`, for the
 * optimistic update. The webhook URL is never optimistic. */
export function applyPatch(prefs: NotificationPreferences, patch: PreferencesPatch): NotificationPreferences {
  const events = { ...prefs.events };
  for (const kind of EVENT_KINDS) {
    const next = patch.events?.[kind];
    if (next) events[kind] = next;
  }
  return {
    ...prefs,
    enabled: patch.enabled ?? prefs.enabled,
    watch_own_assets: patch.watch_own_assets ?? prefs.watch_own_assets,
    email_mode: patch.email_mode ?? prefs.email_mode,
    events,
    chat: patch.chat_enabled === undefined ? prefs.chat : { ...prefs.chat, enabled: patch.chat_enabled },
  };
}

/** The event's channel list with `channel` switched, in the canonical order. */
export function toggleChannel(list: readonly OptionalChannel[], channel: OptionalChannel): OptionalChannel[] {
  const set = new Set(list);
  if (set.has(channel)) set.delete(channel);
  else set.add(channel);
  return CHANNELS.filter((c) => set.has(c));
}

/** Why a channel cannot deliver right now, or null when it can. */
export function channelBlocker(prefs: NotificationPreferences, channel: OptionalChannel): MessageKey | null {
  switch (channel) {
    case "push":
      return prefs.push.available ? null : "accountNotifications.blocked.push";
    case "email":
      if (!prefs.email_available) return "accountNotifications.blocked.emailServer";
      return prefs.email_mode === "off" ? "accountNotifications.blocked.emailOff" : null;
    case "chat":
      if (!prefs.chat.configured) return "accountNotifications.blocked.chatMissing";
      return prefs.chat.enabled ? null : "accountNotifications.blocked.chatOff";
  }
}

/** A space id shown with its middle elided ("spaces/AAAA…xyz0"). */
export function maskSpace(space: string): string {
  return space.length > 16 ? `${space.slice(0, 11)}…${space.slice(-4)}` : space;
}
