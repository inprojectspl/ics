import { useState, type FormEvent } from "react";
import { clsx } from "clsx";
import type { ShareMode } from "../../api";
import { t } from "../../lib/i18n";
import { Field, INPUT_CLASS, TEXTAREA_CLASS } from "../Field";
import { PasswordStrength } from "../PasswordStrength";
import { Button } from "../ui/Button";
import { MODE_INFO, SHARE_MODE_ORDER } from "./shareModes";

export interface NewLink {
  mode: ShareMode;
  password?: string;
  allowed_emails?: string[];
  expires_at: string | null;
  max_views: number | null;
}

interface Props {
  busy: boolean;
  error: string | null;
  /** Resolves true when the link was created; the form then resets. */
  onCreate: (link: NewLink) => Promise<boolean>;
  onInvalid: (message: string) => void;
}

/** A new share link: who may open it, then the optional limits. */
export function NewLinkForm({ busy, error, onCreate, onInvalid }: Props) {
  const [mode, setMode] = useState<ShareMode>("password");
  const [password, setPassword] = useState("");
  const [emails, setEmails] = useState("");
  const [ttlDays, setTtlDays] = useState("");
  const [oneTime, setOneTime] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const allowed = mode === "magic_email" ? emails.split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean) : undefined;
    if (mode === "magic_email" && !allowed?.length) return onInvalid(t("shareDialog.emailsRequired"));
    const ok = await onCreate({
      mode,
      password: mode === "password" ? password : undefined,
      allowed_emails: allowed,
      expires_at: ttlDays ? new Date(Date.now() + Number(ttlDays) * 86400_000).toISOString() : null,
      max_views: oneTime ? 1 : null,
    });
    if (!ok) return;
    setPassword("");
    setEmails("");
    setTtlDays("");
    setOneTime(false);
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <fieldset>
        <legend className="mb-1.5 text-ui font-medium text-text-primary">{t("shareDialog.whoOpens")}</legend>
        <div className="grid gap-2 sm:grid-cols-2">
          {SHARE_MODE_ORDER.map((m) => {
            const info = MODE_INFO[m];
            const on = m === mode;
            return (
              <label
                key={m}
                className={clsx(
                  "flex cursor-pointer gap-3 rounded-card border p-3 transition-colors duration-150",
                  on ? "border-accent bg-accent-soft" : "border-border hover:bg-surface-hover",
                )}
              >
                <input type="radio" name="share-mode" checked={on} onChange={() => setMode(m)} className="mt-0.5 size-4 shrink-0 accent-accent" />
                <span className="min-w-0">
                  <span className="flex items-center gap-1.5 text-ui font-medium text-text-primary">
                    <info.icon size={15} aria-hidden className={on ? "text-accent" : "text-text-secondary"} />
                    {t(info.label)}
                  </span>
                  <span className="mt-0.5 block text-meta text-text-secondary">{t(info.hint)}</span>
                </span>
              </label>
            );
          })}
        </div>
      </fieldset>

      {mode === "password" && (
        <div>
          <Field label={t("shareDialog.passwordLabel")}>
            <input type="text" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} className={INPUT_CLASS} />
          </Field>
          <PasswordStrength password={password} />
        </div>
      )}
      {mode === "magic_email" && (
        <Field label={t("shareDialog.emailsLabel")}>
          <textarea
            value={emails}
            onChange={(e) => setEmails(e.target.value)}
            rows={3}
            placeholder={t("shareDialog.emailsPlaceholder")}
            className={TEXTAREA_CLASS}
          />
        </Field>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t("shareDialog.ttlLabel")}>
          <input
            type="number"
            min={1}
            value={ttlDays}
            onChange={(e) => setTtlDays(e.target.value)}
            placeholder={t("shareDialog.ttlPlaceholder")}
            className={INPUT_CLASS}
          />
        </Field>
        <label className="flex cursor-pointer select-none items-start gap-3 sm:pt-7">
          <input type="checkbox" checked={oneTime} onChange={(e) => setOneTime(e.target.checked)} className="mt-0.5 size-4 shrink-0 accent-accent" />
          <span>
            <span className="block text-ui text-text-primary">{t("shareDialog.oneTime")}</span>
            <span className="block text-meta text-text-secondary">{t("shareDialog.oneTimeHint")}</span>
          </span>
        </label>
      </div>

      {error && (
        <p role="alert" className="text-ui text-danger">
          {error}
        </p>
      )}
      <div className="flex justify-end">
        <Button type="submit" busy={busy}>
          {t("shareDialog.createLink")}
        </Button>
      </div>
    </form>
  );
}
