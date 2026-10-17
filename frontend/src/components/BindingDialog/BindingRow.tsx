import { memo } from "react";
import type {
  Binding,
  NotificationProviderId,
  NotificationProviderInfo,
} from "../../api";
import { formatShortDate } from "../../lib/format";
import { t } from "../../lib/i18n";
import { ProviderSelect, compactInputClasses } from "./_form";

type WebhookDraft = {
  url: string;
  providerId: NotificationProviderId | "";
};

export type EditState = {
  draft: WebhookDraft;
  onUrlChange: (v: string) => void;
  onProviderChange: (id: NotificationProviderId | "") => void;
  onSave: () => void;
  onCancel: () => void;
};

type Props = {
  binding: Binding;
  providers: NotificationProviderInfo[] | null;
  rowBusy: string | null;
  // null when this row is not being edited
  edit: EditState | null;
  onStartEdit: (b: Binding) => void;
  onRotate: (id: string) => void;
  onRemove: (id: string) => void;
};

function BindingRowImpl({
  binding: b,
  providers,
  rowBusy,
  edit,
  onStartEdit,
  onRotate,
  onRemove,
}: Props) {
  const providerLabel = b.provider
    ? providers?.find((p) => p.id === b.provider)?.display_name ?? b.provider
    : null;
  return (
    <li className="rounded-control border border-border p-3">
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="min-w-0 flex-1">
          {b.gitlab_project_url ? (
            <a
              href={b.gitlab_project_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-ui text-accent hover:underline truncate block"
            >
              {b.gitlab_project_url}
            </a>
          ) : (
            <span className="text-ui text-text-secondary">
              {t("bindingRow.noRepo")}
            </span>
          )}
          <div className="text-meta text-text-tertiary mt-0.5">
            {t("bindingRow.created", { date: formatShortDate(b.created_at) })} ·{" "}
            {b.last_sync_at
              ? t("bindingRow.lastSync", { date: formatShortDate(b.last_sync_at) })
              : t("bindingRow.noSyncs")}
          </div>
        </div>
        <div className="flex flex-col gap-1 shrink-0">
          <button
            onClick={() => onRotate(b.id)}
            disabled={rowBusy !== null}
            aria-busy={rowBusy === `rotate:${b.id}` || undefined}
            className="text-meta text-text-tertiary hover:text-accent disabled:opacity-50"
          >
            {rowBusy === `rotate:${b.id}` ? t("bindingRow.rotating") : t("bindingRow.rotate")}
          </button>
          <button
            onClick={() => onRemove(b.id)}
            disabled={rowBusy !== null}
            aria-busy={rowBusy === `delete:${b.id}` || undefined}
            className="text-meta text-text-tertiary hover:text-danger disabled:opacity-50"
          >
            {rowBusy === `delete:${b.id}` ? t("common.deleting") : t("common.delete")}
          </button>
        </div>
      </div>
      <div className="mt-2 space-y-1">
        <span className="mb-1.5 block text-ui font-medium text-text-primary">
          {t("bindingRow.notification")}
        </span>
        {edit ? (
          <WebhookEditForm
            bindingId={b.id}
            providers={providers}
            rowBusy={rowBusy}
            edit={edit}
          />
        ) : (
          <WebhookView binding={b} providerLabel={providerLabel} onStartEdit={onStartEdit} />
        )}
      </div>
      <pre className="font-code text-meta text-text-tertiary bg-surface p-2 rounded-xs overflow-x-auto mt-2">
        {b.public_key.split("\n").slice(0, 2).join("\n") + "\n…"}
      </pre>
    </li>
  );
}

function WebhookEditForm({
  bindingId,
  providers,
  rowBusy,
  edit,
}: {
  bindingId: string;
  providers: NotificationProviderInfo[] | null;
  rowBusy: string | null;
  edit: EditState;
}) {
  const hint =
    edit.draft.providerId
      ? providers?.find((p) => p.id === edit.draft.providerId)?.url_hint ?? "https://…"
      : "https://…";
  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        edit.onSave();
      }}
    >
      <ProviderSelect
        providers={providers}
        value={edit.draft.providerId}
        onChange={edit.onProviderChange}
        compact
      />
      <input
        type="url"
        value={edit.draft.url}
        onChange={(e) => edit.onUrlChange(e.target.value)}
        placeholder={hint}
        className={compactInputClasses}
      />
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={rowBusy !== null}
          aria-busy={rowBusy === `save:${bindingId}` || undefined}
          className="text-meta text-accent hover:underline disabled:opacity-50"
        >
          {rowBusy === `save:${bindingId}` ? t("common.saving") : t("common.save")}
        </button>
        <button
          type="button"
          onClick={edit.onCancel}
          disabled={rowBusy !== null}
          className="text-meta text-text-tertiary hover:text-text-primary disabled:opacity-50"
        >
          {t("common.cancel")}
        </button>
      </div>
    </form>
  );
}

function WebhookView({
  binding: b,
  providerLabel,
  onStartEdit,
}: {
  binding: Binding;
  providerLabel: string | null;
  onStartEdit: (b: Binding) => void;
}) {
  return (
    <div className="flex items-baseline gap-2">
      <span className="font-code text-meta text-text-secondary truncate flex-1 min-w-0">
        {b.webhook_url ? (
          <>
            {providerLabel && (
              <span className="text-text-tertiary mr-1">[{providerLabel}]</span>
            )}
            {b.webhook_url}
          </>
        ) : (
          <span className="text-text-tertiary">{t("bindingRow.noWebhook")}</span>
        )}
      </span>
      <button
        type="button"
        onClick={() => onStartEdit(b)}
        className="text-meta text-text-tertiary hover:text-accent shrink-0"
      >
        {b.webhook_url ? t("common.edit") : t("common.add")}
      </button>
    </div>
  );
}

export const BindingRow = memo(BindingRowImpl);
