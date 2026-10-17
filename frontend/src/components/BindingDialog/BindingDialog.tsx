import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  api,
  AssetSummary,
  Binding,
  BindingWithSecret,
  NotificationProviderId,
} from "../../api";
import { formatApiError } from "../../lib/apiError";
import { t } from "../../lib/i18n";
import {
  describeWebhookUrlError,
  validateWebhookPair,
  validateWebhookUrl,
} from "../../lib/notificationProviders";
import { qk } from "../../lib/queries";
import { useConfirm } from "../ConfirmDialog";
import { PrimaryButton } from "../Form";
import { Dialog } from "../ui/Dialog";
import { BindingRow, EditState } from "./BindingRow";
import { FormLabel, ProviderSelect, textInputClasses } from "./_form";
import { SecretReveal } from "./SecretReveal";

interface Props {
  asset: AssetSummary;
  onClose: () => void;
}

export function BindingDialog({ asset, onClose }: Props) {
  const [bindings, setBindings] = useState<Binding[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // rowBusy is the key of the action in progress ("rotate:<id>" / "save:<id>" /
  // "delete:<id>"): it disables all row actions of the group and shows the
  // busy label only on the clicked button.
  const [rowBusy, setRowBusy] = useState<string | null>(null);
  const [gitlabUrl, setGitlabUrl] = useState("");
  const [webhookUrl, setWebhookUrl] = useState("");
  // null until the user picks; "" is an explicit "No notification".
  const [pickedProviderId, setProviderId] = useState<NotificationProviderId | "" | null>(null);
  const [secret, setSecret] = useState<BindingWithSecret | null>(null);
  const [editingFor, setEditingFor] = useState<string | null>(null);
  const [webhookDraft, setWebhookDraft] = useState("");
  const [providerDraft, setProviderDraft] = useState<NotificationProviderId | "">("");
  const confirm = useConfirm();

  // The provider list is static (an import-time registry on the backend), so
  // it is cached for the app's lifetime and reopening the modal skips the API.
  const providersQuery = useQuery({
    queryKey: qk.notificationProviders(),
    queryFn: api.listNotificationProviders,
    staleTime: Infinity,
    gcTime: Infinity,
  });
  const providers = providersQuery.data ?? null;

  // Default to the first provider; the backend sorts the list by display_name,
  // so the order is stable.
  const providerId = pickedProviderId ?? providers?.[0]?.id ?? "";

  const refresh = useCallback(
    () => api.listBindings(asset.id).then(setBindings, (e) => setError(formatApiError(e))),
    [asset.id],
  );

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const selectedProvider = providerId
    ? providers?.find((p) => p.id === providerId)
    : undefined;
  const createUrlError = useMemo(() => {
    if (!providerId || !webhookUrl.trim()) return null;
    const err = validateWebhookUrl(providerId, webhookUrl);
    return err ? describeWebhookUrlError(err) : null;
  }, [providerId, webhookUrl]);

  const create = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    const pairError = validateWebhookPair(providerId, webhookUrl);
    if (pairError) {
      setError(pairError);
      return;
    }
    setBusy(true);
    try {
      const created = await api.createBinding(asset.id, {
        gitlabUrl: gitlabUrl.trim() || undefined,
        webhook:
          providerId && webhookUrl.trim()
            ? { url: webhookUrl.trim(), provider: providerId }
            : undefined,
      });
      setSecret(created);
      setGitlabUrl("");
      setWebhookUrl("");
      await refresh();
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  };

  const startEdit = useCallback((b: Binding) => {
    setEditingFor(b.id);
    setWebhookDraft(b.webhook_url ?? "");
    setProviderDraft(b.provider ?? "");
  }, []);

  const cancelEdit = useCallback(() => {
    setEditingFor(null);
    setWebhookDraft("");
    setProviderDraft("");
  }, []);

  // The rowBusy guard runs only before the await: after it the closure snapshot
  // would be stale, and setRowBusy() is the sole arbiter anyway (a second
  // click lands on a disabled button).
  const saveWebhook = useCallback(
    async (id: string) => {
      setError(null);
      const pairError = validateWebhookPair(providerDraft, webhookDraft);
      if (pairError) {
        setError(pairError);
        return;
      }
      const url = webhookDraft.trim();
      setRowBusy(`save:${id}`);
      try {
        await api.patchBinding(id, {
          webhook:
            url && providerDraft ? { url, provider: providerDraft } : null,
        });
        cancelEdit();
        await refresh();
      } catch (e) {
        setError(formatApiError(e));
      } finally {
        setRowBusy(null);
      }
    },
    [webhookDraft, providerDraft, cancelEdit, refresh],
  );

  const rotate = useCallback(
    async (id: string) => {
      const ok = await confirm({
        title: t("bindingDialog.rotateTitle"),
        message: t("bindingDialog.rotateMessage"),
        confirmLabel: t("bindingDialog.rotateConfirm"),
        destructive: true,
      });
      if (!ok) return;
      setRowBusy(`rotate:${id}`);
      try {
        const rotated = await api.rotateBinding(id);
        setSecret(rotated);
        await refresh();
      } catch (e) {
        setError(formatApiError(e));
      } finally {
        setRowBusy(null);
      }
    },
    [confirm, refresh],
  );

  const remove = useCallback(
    async (id: string) => {
      const ok = await confirm({
        title: t("bindingDialog.removeTitle"),
        message: t("bindingDialog.removeMessage"),
        confirmLabel: t("common.delete"),
        destructive: true,
      });
      if (!ok) return;
      setRowBusy(`delete:${id}`);
      try {
        await api.deleteBinding(id);
        await refresh();
      } catch (e) {
        setError(formatApiError(e));
      } finally {
        setRowBusy(null);
      }
    },
    [confirm, refresh],
  );

  const editStateFor = useCallback(
    (b: Binding): EditState | null =>
      editingFor === b.id
        ? {
            draft: { url: webhookDraft, providerId: providerDraft },
            onUrlChange: setWebhookDraft,
            onProviderChange: setProviderDraft,
            onSave: () => saveWebhook(b.id),
            onCancel: cancelEdit,
          }
        : null,
    [editingFor, webhookDraft, providerDraft, saveWebhook, cancelEdit],
  );

  return (
    <Dialog
      eyebrow={t("bindingDialog.eyebrow")}
      title={asset.title || asset.slug}
      onClose={onClose}
      maxWidth="2xl"
    >
      {secret && <SecretReveal asset={asset} secret={secret} onDismiss={() => setSecret(null)} />}

      {!secret && (
        <>
          <section className="px-6 py-5 border-b border-border">
            <h3 className="text-ui font-semibold text-text-primary mb-2">
              {t("bindingDialog.newTitle")}
            </h3>
            <p className="text-meta text-text-tertiary mb-4">
              {t("bindingDialog.introBefore")}{" "}
              <strong className="text-text-primary">{t("bindingDialog.introOnce")}</strong>
              {t("bindingDialog.introAfter")}
            </p>
            <form onSubmit={create} className="space-y-3">
              <FormLabel text={t("bindingDialog.gitlabUrl")}>
                <input
                  type="url"
                  value={gitlabUrl}
                  onChange={(e) => setGitlabUrl(e.target.value)}
                  placeholder="https://gitlab.example.com/team/repo"
                  className={textInputClasses}
                />
              </FormLabel>
              <FormLabel text={t("bindingDialog.notification")}>
                <ProviderSelect
                  providers={providers}
                  value={providerId}
                  onChange={setProviderId}
                />
              </FormLabel>
              <FormLabel text="Webhook URL">
                <input
                  type="url"
                  value={webhookUrl}
                  onChange={(e) => setWebhookUrl(e.target.value)}
                  placeholder={selectedProvider?.url_hint ?? "https://…"}
                  className={textInputClasses}
                />
                {createUrlError ? (
                  <span className="block text-meta text-danger mt-1">
                    {createUrlError}
                  </span>
                ) : selectedProvider ? (
                  <span className="block text-meta text-text-tertiary mt-1">
                    {t("bindingDialog.providerHintBefore")}{" "}
                    <strong>{selectedProvider.display_name}</strong>{" "}
                    {t("bindingDialog.providerHintAfter")}
                  </span>
                ) : null}
              </FormLabel>
              <PrimaryButton type="submit" busy={busy} className="w-full">
                {busy ? t("bindingDialog.generating") : t("bindingDialog.create")}
              </PrimaryButton>
            </form>
            {error && <p className="text-ui text-danger mt-3">{error}</p>}
          </section>

          <section className="px-6 py-5">
            <h3 className="text-ui font-semibold text-text-primary mb-3">
              {t("bindingDialog.activeTitle")}
            </h3>
            {bindings === null && <p className="text-text-tertiary text-meta">{t("common.loading")}</p>}
            {bindings && bindings.length === 0 && (
              <p className="text-text-tertiary text-meta">{t("bindingDialog.none")}</p>
            )}
            <ul className="space-y-3">
              {bindings?.map((b) => (
                <BindingRow
                  key={b.id}
                  binding={b}
                  providers={providers}
                  rowBusy={rowBusy}
                  edit={editStateFor(b)}
                  onStartEdit={startEdit}
                  onRotate={rotate}
                  onRemove={remove}
                />
              ))}
            </ul>
          </section>
        </>
      )}
    </Dialog>
  );
}
