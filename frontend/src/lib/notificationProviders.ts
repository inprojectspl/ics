// Frontend-side provider URL validation. The backend holds the authoritative
// copy (services/notifications/_providers/*.accepts_url), but a local copy
// gives instant feedback without a 400 round trip. The switch on
// NotificationProviderId enforces exhaustiveness, so adding a new provider
// in types.ts is a compile error here.
import type { NotificationProviderId } from "../api/types";
import { t, type MessageKey } from "./i18n";

export type WebhookUrlError =
  | "empty"
  | "malformed"
  | "wrong_scheme"
  | "wrong_host"
  | "has_userinfo";

const MESSAGES: Record<WebhookUrlError, MessageKey> = {
  empty: "notificationProviders.urlEmpty",
  malformed: "notificationProviders.urlMalformed",
  wrong_scheme: "notificationProviders.urlWrongScheme",
  wrong_host: "notificationProviders.urlWrongHost",
  has_userinfo: "notificationProviders.urlHasUserinfo",
};

export function describeWebhookUrlError(err: WebhookUrlError): string {
  return t(MESSAGES[err]);
}

export function validateWebhookUrl(
  providerId: NotificationProviderId,
  url: string,
): WebhookUrlError | null {
  if (!url.trim()) return "empty";
  let parsed: URL;
  try {
    parsed = new URL(url.trim());
  } catch {
    return "malformed";
  }
  switch (providerId) {
    case "google_chat":
      if (parsed.protocol !== "https:") return "wrong_scheme";
      if (parsed.username || parsed.password) return "has_userinfo";
      if (parsed.hostname.toLowerCase() !== "chat.googleapis.com") {
        return "wrong_host";
      }
      return null;
  }
}

// Validates the (provider, url) pair together, for the create and edit forms
// in BindingDialog. Returns a localized message, or null when the pair is
// valid (both empty means no notifications, which is fine).
export function validateWebhookPair(
  providerId: NotificationProviderId | "",
  url: string,
): string | null {
  const trimmed = url.trim();
  if (!trimmed && !providerId) return null;
  if (trimmed && !providerId) return t("notificationProviders.providerRequired");
  if (!trimmed && providerId) return null;
  const err = validateWebhookUrl(providerId as NotificationProviderId, trimmed);
  return err ? describeWebhookUrlError(err) : null;
}
