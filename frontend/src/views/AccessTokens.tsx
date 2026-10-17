import { FormEvent, useState } from "react";
import { clsx } from "clsx";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy } from "lucide-react";

import { api, type AccessToken, type CreatedAccessToken, type Me } from "../api";
import { Button } from "../components/ui/Button";
import { Field, inputClass } from "../components/Field";
import { useConfirm } from "../components/ConfirmDialog";
import { PageHeader } from "../components/ui/PageHeader";
import { AccountPage } from "../components/AccountPage";
import { formatApiError } from "../lib/apiError";
import { formatDay, formatTimestamp } from "../lib/format";
import { t } from "../lib/i18n";
import { qk } from "../lib/queries";
import { useClipboard } from "../lib/useClipboard";

interface Props {
  me: Me;
}

// Backend limit (ADR-0020): a token lives at most 180 days.
const MAX_DAYS = 180;
const DEFAULT_DAYS = 90;

/** `YYYY-MM-DD` of today plus `days`, in UTC like the value sent. */
export function dayOffset(days: number, now: Date = new Date()): string {
  const d = new Date(now);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

const INPUT = inputClass({ size: "lg" });

/**
 * The caller's personal access tokens, for agents and scripts reading ICS
 * (ADR-0020). The secret is shown once, right after creation; the list only
 * ever has the prefix.
 */
export function AccessTokens({ me }: Props) {
  const queryClient = useQueryClient();
  const list = useQuery({ queryKey: qk.accessTokens(), queryFn: api.listTokens });
  const tokens = list.data?.items ?? null;
  const [created, setCreated] = useState<CreatedAccessToken | null>(null);
  const [name, setName] = useState("");
  const [expiry, setExpiry] = useState(() => dayOffset(DEFAULT_DAYS));
  const [busy, setBusy] = useState(false);
  const [actionError, setError] = useState<string | null>(null);
  const error = actionError ?? (list.error ? formatApiError(list.error) : null);
  const { copy, copiedKey } = useClipboard();
  const confirm = useConfirm();

  const refresh = () => queryClient.invalidateQueries({ queryKey: qk.accessTokens() });

  const minDate = dayOffset(1);
  const maxDate = dayOffset(MAX_DAYS);

  const onCreate = async (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      // Start of the chosen day (UTC): the last allowed day stays within 180 days.
      const token = await api.createToken(name.trim(), `${expiry}T00:00:00Z`);
      setCreated(token);
      setName("");
      await refresh();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  };

  const onRevoke = async (token: AccessToken) => {
    const ok = await confirm({
      title: t("accessTokens.revokeTitle", { name: token.name }),
      message: t("accessTokens.revokeBody"),
      confirmLabel: t("accessTokens.revoke"),
      destructive: true,
    });
    if (!ok) return;
    setError(null);
    try {
      await api.revokeToken(token.id);
      if (created?.id === token.id) setCreated(null);
      await refresh();
    } catch (err) {
      setError(formatApiError(err));
    }
  };

  return (
    <AccountPage me={me} tab="tokens">
      <PageHeader title={t("accessTokens.title")} description={t("accessTokens.intro")} />

      {created && (
        <section
          aria-label={t("accessTokens.createdTitle")}
          className="mb-8 rounded-card border border-accent/40 bg-accent/5 p-4"
        >
          <h2 className="text-ui font-semibold text-text-primary mb-1">
            {t("accessTokens.createdTitle")}
          </h2>
          <p className="text-ui text-text-secondary mb-3">{t("accessTokens.createdHint")}</p>
          <div className="flex items-center gap-2">
            <code className="flex-1 min-w-0 break-all font-code text-meta text-text-primary bg-surface border border-border rounded-control px-3 py-2">
              {created.token}
            </code>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => void copy(created.token, "token")}
              aria-label={t("accessTokens.copy")}
            >
              {copiedKey === "token" ? <Check size={14} aria-hidden /> : <Copy size={14} aria-hidden />}
              {copiedKey === "token" ? t("accessTokens.copied") : t("accessTokens.copy")}
            </Button>
          </div>
          <div className="flex justify-end mt-3">
            <Button variant="ghost" size="sm" onClick={() => setCreated(null)}>
              {t("accessTokens.done")}
            </Button>
          </div>
        </section>
      )}

      {error && (
        <p role="alert" className="text-ui text-danger mb-4">
          {error}
        </p>
      )}

      <section className="mb-10">
        {tokens === null ? (
          <p className="text-meta text-text-tertiary">{t("common.loading")}</p>
        ) : tokens.length === 0 ? (
          <p className="text-meta text-text-tertiary">{t("accessTokens.empty")}</p>
        ) : (
          <ul aria-label={t("accessTokens.listLabel")}>
            {tokens.map((tok) => (
              <li key={tok.id} className="flex items-center justify-between gap-4 py-3 border-b border-border">
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline gap-3 flex-wrap">
                    <span className="text-body text-text-primary">{tok.name}</span>
                    <code className="font-code text-meta text-text-tertiary">{`ics_pat_${tok.prefix}_…`}</code>
                    <span className="font-code text-meta text-text-tertiary">{tok.scopes.join(", ")}</span>
                  </div>
                  <div className="text-meta text-text-tertiary mt-0.5">
                    {t("accessTokens.expires", { date: formatDay(tok.expires_at) })}
                    {" · "}
                    {tok.last_used_at
                      ? t("accessTokens.lastUsed", { when: formatTimestamp(tok.last_used_at) })
                      : t("accessTokens.neverUsed")}
                  </div>
                </div>
                <Button variant="danger" size="sm" onClick={() => void onRevoke(tok)}>
                  {t("accessTokens.revoke")}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h2 className="text-meta text-text-secondary mb-3 font-medium">
          {t("accessTokens.createTitle")}
        </h2>
        <form onSubmit={onCreate} className="card space-y-3 px-1">
          <Field label={t("accessTokens.nameLabel")}>
            <input
              value={name}
              maxLength={100}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("accessTokens.namePlaceholder")}
              className={INPUT}
            />
          </Field>
          <Field label={t("accessTokens.expiryLabel")} hint={t("accessTokens.expiryHint", { days: MAX_DAYS })}>
            <input
              type="date"
              value={expiry}
              min={minDate}
              max={maxDate}
              onChange={(e) => setExpiry(e.target.value)}
              className={clsx(INPUT, "font-code")}
            />
          </Field>
          <div className="flex justify-end">
            <Button
              type="submit"
              disabled={busy || !name.trim() || expiry < minDate || expiry > maxDate}
            >
              {busy ? t("common.creating") : t("accessTokens.create")}
            </Button>
          </div>
        </form>
      </section>
    </AccountPage>
  );
}
