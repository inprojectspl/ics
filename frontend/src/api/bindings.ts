import { postJson, req } from "./_core";
import type {
  Binding,
  BindingWithSecret,
  NotificationProviderId,
  NotificationProviderInfo,
} from "./types";

// The webhook_url + provider pair is atomic on the backend: either both
// are undefined (notifications off) or both are set.
export type WebhookConfig = {
  url: string;
  provider: NotificationProviderId;
};

export const listBindings = (assetId: string) =>
  req<Binding[]>(`/api/bindings?asset_id=${assetId}`);

export const listNotificationProviders = () =>
  req<NotificationProviderInfo[]>("/api/bindings/providers");

export const createBinding = (
  assetId: string,
  opts: { gitlabUrl?: string; webhook?: WebhookConfig } = {},
) =>
  postJson<BindingWithSecret>("/api/bindings", {
    asset_id: assetId,
    gitlab_project_url: opts.gitlabUrl || null,
    webhook_url: opts.webhook?.url ?? null,
    provider: opts.webhook?.provider ?? null,
  });

export const patchBinding = (
  bindingId: string,
  patch: {
    gitlab_project_url?: string | null;
    // webhook=null clears the pair, a WebhookConfig sets it, undefined leaves it.
    webhook?: WebhookConfig | null;
  },
) => {
  // Map `webhook` to the (provider, webhook_url) pair; the backend's fields_set
  // decides whether the pair changes (both present) or not (both omitted).
  // `null` means clear (both fields sent as null).
  const body: Record<string, unknown> = {};
  if (patch.gitlab_project_url !== undefined) {
    body.gitlab_project_url = patch.gitlab_project_url;
  }
  if (patch.webhook !== undefined) {
    body.webhook_url = patch.webhook?.url ?? null;
    body.provider = patch.webhook?.provider ?? null;
  }
  return req<Binding>(`/api/bindings/${bindingId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
};

export const rotateBinding = (bindingId: string) =>
  req<BindingWithSecret>(`/api/bindings/${bindingId}/rotate`, { method: "POST" });

export const deleteBinding = (bindingId: string) =>
  req<void>(`/api/bindings/${bindingId}`, { method: "DELETE" });
