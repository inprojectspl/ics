import { FormEvent, useCallback, useEffect, useState } from "react";
import { clsx } from "clsx";
import { Globe, Lock, Plus, Trash2 } from "lucide-react";
import { api, Me } from "../api";
import { AdminPage } from "../components/AdminPage";
import { useConfirm } from "../components/ConfirmDialog";
import { EmptyState } from "../components/EmptyState";
import { Field, INPUT_CLASS } from "../components/Field";
import { Button } from "../components/ui/Button";
import { DATA_ROW, DataList, dataRow } from "../components/ui/DataList";
import { Dialog } from "../components/ui/Dialog";
import { Disclosure } from "../components/ui/Disclosure";
import { IconButton } from "../components/ui/IconButton";
import { PageHeader } from "../components/ui/PageHeader";
import { formatApiError } from "../lib/apiError";
import { formatDay } from "../lib/format";
import { t, tn } from "../lib/i18n";

interface Props {
  me: Me;
}

type Listing = Awaited<ReturnType<typeof api.adminCdnList>>;

/**
 * Hosts an HTML bundle may load scripts from without being held for review.
 * The hosts admins added come first and are the only ones that change; the
 * built-in base from the deployment config is listed below, folded.
 */
export function AdminCdn({ me }: Props) {
  const [data, setData] = useState<Listing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const confirm = useConfirm();

  const refresh = useCallback(
    () => api.adminCdnList().then(setData, (e) => setError(formatApiError(e))),
    [],
  );

  useEffect(() => {
    if (me.role !== "admin") return;
    void refresh();
  }, [me.role, refresh]);

  const remove = async (id: string, host: string) => {
    const ok = await confirm({
      title: t("adminCdn.removeTitle", { host }),
      message: t("adminCdn.removeBody"),
      confirmLabel: t("common.delete"),
      destructive: true,
    });
    if (!ok) return;
    setError(null);
    try {
      await api.adminCdnRemove(id);
      await refresh();
    } catch (e) {
      setError(formatApiError(e));
    }
  };

  const runtime = data?.runtime ?? [];
  const builtin = data?.builtin ?? [];

  return (
    <AdminPage me={me} tab="cdn">
      <PageHeader
        title={t("adminCdn.title")}
        description={t("adminCdn.intro")}
        actions={
          <Button icon={<Plus size={16} aria-hidden />} onClick={() => setAdding(true)}>
            {t("adminCdn.addHost")}
          </Button>
        }
      />

      {error && (
        <p role="alert" className="mb-4 text-ui text-danger">
          {error}
        </p>
      )}

      <section aria-labelledby="cdn-runtime" className="mb-8">
        <h2 id="cdn-runtime" className="mb-2 text-ui font-semibold text-text-primary">
          {t("adminCdn.runtime")}
        </h2>
        {data && runtime.length === 0 ? (
          <EmptyState compact icon={Globe} title={t("adminCdn.runtimeEmptyTitle")} description={t("adminCdn.runtimeEmpty")} />
        ) : (
          <DataList label={t("adminCdn.runtime")}>
            {runtime.map((r) => (
              <li key={r.id} className={DATA_ROW}>
                <Globe size={18} aria-hidden className="shrink-0 text-text-secondary" />
                <div className="min-w-0 flex-1">
                  <p className="font-code text-ui font-medium text-text-primary [overflow-wrap:anywhere]">{r.host}</p>
                  <p className="text-meta text-text-secondary">
                    {r.note ? `${r.note} · ` : ""}
                    {t("adminCdn.addedOn", { date: formatDay(r.created_at) })}
                  </p>
                </div>
                <IconButton
                  label={t("adminCdn.removeHost", { host: r.host })}
                  icon={<Trash2 size={16} aria-hidden />}
                  onClick={() => void remove(r.id, r.host)}
                />
              </li>
            ))}
          </DataList>
        )}
      </section>

      <Disclosure
        title={t("adminCdn.builtin")}
        aside={<span className="text-meta text-text-secondary tabular-nums">{tn("adminCdn.hostCount", builtin.length)}</span>}
      >
        <p className="mb-3 text-ui text-text-secondary">{t("adminCdn.builtinNote")}</p>
        <DataList label={t("adminCdn.builtin")} className="shadow-none">
          {builtin.map((h) => (
            <li key={h} className={dataRow({ interactive: false })}>
              <Lock size={16} aria-hidden className="shrink-0 text-text-tertiary" />
              <span className="min-w-0 font-code text-ui text-text-secondary [overflow-wrap:anywhere]">{h}</span>
            </li>
          ))}
        </DataList>
      </Disclosure>

      {adding && (
        <AddHostDialog
          onClose={() => setAdding(false)}
          onAdded={async () => {
            setAdding(false);
            await refresh();
          }}
        />
      )}
    </AdminPage>
  );
}

function AddHostDialog({ onClose, onAdded }: { onClose: () => void; onAdded: () => Promise<void> }) {
  const [host, setHost] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const value = host.trim().toLowerCase();
    if (!value || busy) return;
    setBusy(true);
    setError(null);
    try {
      await api.adminCdnAdd(value, note.trim() || undefined);
      await onAdded();
    } catch (err) {
      setError(formatApiError(err));
      setBusy(false);
    }
  };

  return (
    <Dialog title={t("adminCdn.addHost")} onClose={onClose} maxWidth="lg">
      <form onSubmit={submit} className="space-y-4 px-5 py-5 sm:px-6">
        <Field label={t("adminCdn.hostLabel")} hint={t("adminCdn.hostHint")}>
          <input
            autoFocus
            required
            value={host}
            onChange={(e) => setHost(e.target.value)}
            placeholder={t("adminCdn.hostPlaceholder")}
            autoCapitalize="none"
            spellCheck={false}
            className={clsx(INPUT_CLASS, "font-code")}
          />
        </Field>
        <Field label={t("adminCdn.noteLabel")}>
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder={t("adminCdn.notePlaceholder")}
            className={INPUT_CLASS}
          />
        </Field>
        {error && (
          <p role="alert" className="text-ui text-danger">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" busy={busy} disabled={!host.trim()}>
            {t("adminCdn.submit")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
