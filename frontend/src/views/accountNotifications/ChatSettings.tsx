import { useState, type FormEvent } from "react";
import { AlertTriangle, Send } from "lucide-react";
import { sendChatTest, updatePreferences } from "../../api/notifications";
import type { NotificationPreferences } from "../../api/notificationTypes";
import { Button } from "../../components/ui/Button";
import { useConfirm } from "../../components/ConfirmDialog";
import { inputClass } from "../../components/Field";
import { Switch } from "../../components/Switch";
import { useToast } from "../../components/Toast";
import { formatApiError } from "../../lib/apiError";
import { messageForCode } from "../../lib/errorMessages";
import { t } from "../../lib/i18n";
import { describeWebhookUrlError, validateWebhookUrl } from "../../lib/notificationProviders";
import { maskSpace } from "../../lib/notifications/preferences";
import type { PrefsProps } from "./_shared";

interface Props extends PrefsProps {
  onSaved: (prefs: NotificationPreferences) => void;
}

/**
 * Personal Google Chat webhook. The URL is a secret the server never
 * returns: after saving only the space id is shown.
 */
export function ChatSettings({ prefs, update, onSaved }: Props) {
  const { chat } = prefs;
  const { toast } = useToast();
  const confirm = useConfirm();
  const [url, setUrl] = useState("");
  const [editing, setEditing] = useState(!chat.configured);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async (e: FormEvent) => {
    e.preventDefault();
    const invalid = validateWebhookUrl("google_chat", url);
    if (invalid) {
      setError(describeWebhookUrlError(invalid));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      onSaved(await updatePreferences({ chat_webhook_url: url.trim() }));
      setUrl("");
      setEditing(false);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    const ok = await confirm({
      title: t("accountNotifications.chatRemoveTitle"),
      message: t("accountNotifications.chatRemoveBody"),
      confirmLabel: t("accountNotifications.chatRemove"),
      destructive: true,
    });
    if (!ok) return;
    try {
      onSaved(await updatePreferences({ chat_webhook_url: null }));
      setEditing(true);
    } catch (err) {
      toast(formatApiError(err), "error");
    }
  };

  const test = async () => {
    try {
      await sendChatTest();
      toast(t("accountNotifications.chatTestSent"), "success");
    } catch (err) {
      toast(formatApiError(err), "error");
    }
  };

  return (
    <div className="space-y-3">
      <p className="flex items-start gap-2 rounded-control bg-warning/10 px-3 py-2 text-meta text-text-secondary">
        <AlertTriangle size={14} aria-hidden className="mt-0.5 shrink-0 text-warning" />
        {t("accountNotifications.chatWarning")}
      </p>

      {chat.configured && chat.space && (
        <p className="text-ui text-text-primary">
          {t("accountNotifications.chatSpace")}{" "}
          <code className="font-code text-meta text-text-secondary" title={chat.space}>
            {maskSpace(chat.space)}
          </code>
        </p>
      )}

      {chat.error_code && (
        <p role="alert" className="text-meta text-danger">
          {t("accountNotifications.chatFailed")}{" "}
          {messageForCode(chat.error_code) ?? t("accountNotifications.chatErrorCode", { code: chat.error_code })}
        </p>
      )}

      {chat.configured && (
        <Switch
          checked={chat.enabled}
          onChange={(chat_enabled) => update({ chat_enabled })}
          label={t("accountNotifications.chatEnabled")}
        />
      )}

      {editing ? (
        <form onSubmit={(e) => void save(e)} className="flex flex-col sm:flex-row gap-2">
          <label className="flex-1 min-w-0">
            <span className="sr-only">{t("accountNotifications.chatUrlLabel")}</span>
            <input
              type="url"
              inputMode="url"
              autoComplete="off"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://chat.googleapis.com/v1/spaces/…"
              className={`${inputClass({ size: "lg" })} font-code`}
            />
          </label>
          <div className="flex gap-2">
            <Button type="submit" size="sm" disabled={busy || !url.trim()}>
              {busy ? t("common.saving") : t("common.save")}
            </Button>
            {chat.configured && (
              <Button variant="ghost" size="sm" onClick={() => setEditing(false)}>
                {t("common.cancel")}
              </Button>
            )}
          </div>
        </form>
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" size="sm" onClick={() => void test()} disabled={!chat.enabled}>
            <Send size={14} aria-hidden />
            {t("accountNotifications.chatTest")}
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setEditing(true)}>
            {t("accountNotifications.chatReplace")}
          </Button>
          <Button variant="danger" size="sm" onClick={() => void remove()}>
            {t("accountNotifications.chatRemove")}
          </Button>
        </div>
      )}
      {error && (
        <p role="alert" className="text-meta text-danger">
          {error}
        </p>
      )}
    </div>
  );
}
