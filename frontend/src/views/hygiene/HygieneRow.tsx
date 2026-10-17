import { clsx } from "clsx";
import { memo, useState } from "react";

import { api, type DocTypeInfo, type HygieneItem, type HygieneList } from "../../api";
import { Button, buttonClass } from "../../components/ui/Button";
import { formatApiError } from "../../lib/apiError";
import { formatShortDate } from "../../lib/format";
import { t, tn } from "../../lib/i18n";
import { BasisChanges } from "./BasisChanges";
import { findSuccessor, moveExternalRefs } from "./repoint";
import { INPUT_CLASS, TEXTAREA_CLASS } from "../../components/Field";
import { SUMMARY_MAX } from "../../components/AssetMetaDialog";

type ConfirmFn = (opts: { title: string; message: string; confirmLabel: string }) => Promise<boolean>;

interface Props {
  item: HygieneItem;
  list: HygieneList;
  docTypes: DocTypeInfo[];
  /** Called after a successful fix; reloads the page and its counters. */
  onDone: (message: string) => void;
  onError: (message: string) => void;
  confirm: ConfirmFn;
}

/** One document on a hygiene list with the fix that list calls for. */
export const HygieneRow = memo(function HygieneRow({ item, list, docTypes, onDone, onError, confirm }: Props) {
  const [busy, setBusy] = useState(false);
  const [summary, setSummary] = useState<string | null>(null);
  const [showBasis, setShowBasis] = useState(false);
  const title = item.title || item.slug;

  const run = async (write: () => Promise<unknown>, message: string) => {
    setBusy(true);
    try {
      await write();
      onDone(message);
    } catch (e) {
      onError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  };

  const editSummary = () => {
    setSummary("");
    // A stale description is edited, not written from scratch.
    if (list === "summary_stale") {
      api.getAssetMeta(item.slug).then(
        (meta) => setSummary((s) => (s ? s : (meta.summary ?? ""))),
        () => undefined,
      );
    }
  };

  const repoint = async () => {
    setBusy(true);
    try {
      const successor = await findSuccessor(item.slug);
      if (!successor) {
        onError(t("hygiene.noSuccessor"));
        return;
      }
      const name = successor.title || successor.slug;
      const ok = await confirm({
        title: t("hygiene.repointTitle", { name }),
        message: t("hygiene.repointBody"),
        confirmLabel: t("hygiene.repoint"),
      });
      if (!ok) return;
      const moved = await moveExternalRefs(item.id, successor.id);
      onDone(tn("hygiene.repointed", moved));
    } catch (e) {
      onError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className="border border-border rounded-control bg-surface px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <div className="flex-1 min-w-[12rem]">
          <a href={`/v/${item.slug}`} className="font-medium text-text-primary hover:text-accent break-words">
            {title}
          </a>
          <p className="text-meta text-text-tertiary">
            {t("hygiene.version", { version: item.version })}
            {item.review_due_at && ` · ${t("hygiene.reviewDue", { date: formatShortDate(item.review_due_at) })}`}
            {item.hidden_edges != null && ` · ${tn("hygiene.hiddenCount", item.hidden_edges)}`}
          </p>
        </div>
        {(list === "no_summary" || list === "summary_stale") && summary === null && (
          <Button size="sm" variant="secondary" disabled={busy} onClick={editSummary}>
            {t(list === "no_summary" ? "assetMeta.addSummary" : "assetMeta.editSummary")}
          </Button>
        )}
        {list === "no_doc_type" && (
          <select
            aria-label={t("hygiene.pickDocType", { title })}
            disabled={busy}
            value=""
            onChange={(e) =>
              void run(() => api.patchMeta(item.id, { doc_type: e.target.value }), t("hygiene.saved"))
            }
            className={INPUT_CLASS}
          >
            <option value="" disabled>
              {t("hygiene.pickDocTypePlaceholder")}
            </option>
            {docTypes
              .filter((d) => !d.archived)
              .map((d) => (
                <option key={d.key} value={d.key}>
                  {d.label}
                </option>
              ))}
          </select>
        )}
        {list === "review_overdue" && (
          <Button
            size="sm"
            variant="secondary"
            disabled={busy}
            title={t("assetMeta.stillCurrentTitle")}
            onClick={() => void run(() => api.markReviewed(item.id), t("hygiene.reviewed"))}
          >
            {t("assetMeta.stillCurrent")}
          </Button>
        )}
        {list === "basis_changed" && (
          <Button size="sm" variant="secondary" aria-expanded={showBasis} onClick={() => setShowBasis((v) => !v)}>
            {t("hygiene.showChanges")}
          </Button>
        )}
        {list === "superseded_linked" && (
          <Button size="sm" variant="secondary" disabled={busy} onClick={() => void repoint()}>
            {t("hygiene.repoint")}
          </Button>
        )}
        <a href={`/v/${item.slug}`} className={buttonClass("ghost", "sm")}>
          {t("common.open")}
        </a>
      </div>

      {summary !== null && (
        <form
          className="mt-3 space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            void run(() => api.patchMeta(item.id, { summary: summary.trim() }), t("hygiene.saved"));
          }}
        >
          <textarea
            aria-label={t("hygiene.summaryFor", { title })}
            value={summary}
            maxLength={SUMMARY_MAX}
            rows={3}
            autoFocus
            onChange={(e) => setSummary(e.target.value)}
            className={clsx(TEXTAREA_CLASS, "w-full")}
          />
          <div className="flex gap-2 justify-end">
            <Button size="sm" variant="ghost" onClick={() => setSummary(null)} disabled={busy}>
              {t("common.cancel")}
            </Button>
            <Button size="sm" type="submit" disabled={busy || !summary.trim()}>
              {busy ? t("common.saving") : t("common.save")}
            </Button>
          </div>
        </form>
      )}
      {showBasis && (
        <div className="mt-3 border-t border-border pt-3">
          <BasisChanges slug={item.slug} onDone={() => onDone(t("hygiene.saved"))} onError={onError} />
        </div>
      )}
    </li>
  );
});
