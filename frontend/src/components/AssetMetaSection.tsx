import { useState } from "react";
import { clsx } from "clsx";
import { CheckCircle2, Pencil, Plus, SlidersHorizontal } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type AssetMetaDetail, type AssetMetaView, type AssetSummary } from "../api";
import { formatApiError } from "../lib/apiError";
import { canEdit } from "../lib/assetRoles";
import { formatDateTime, formatDay } from "../lib/format";
import { t } from "../lib/i18n";
import { qk } from "../lib/queries";
import { DocTypeBadge, FreshnessBadge } from "./AssetMetaBadges";
import { AssetMetaDialog, SUMMARY_MAX, type Person } from "./AssetMetaDialog";
import { PanelAction, PanelSection } from "./ui/PanelSection";
import { TEXTAREA_CLASS } from "./Field";

interface Props {
  asset: AssetSummary;
  /** Called after a metadata write, so lists showing the asset refetch. */
  onChanged: () => void | Promise<void>;
}

/**
 * "What is this document" block at the top of the reader panel: the summary,
 * its doc type and freshness, who maintains it and when the content changed.
 * Editors write the summary and confirm an overdue document is still current;
 * readers only see it.
 */
export function AssetMetaSection({ asset, onChanged }: Props) {
  const queryClient = useQueryClient();
  const { data: meta } = useQuery({
    queryKey: qk.assetMeta(asset.slug),
    queryFn: () => api.getAssetMeta(asset.slug),
  });
  const [draft, setDraft] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const editor = canEdit(asset);

  if (!meta) return null;

  // The write response is authoritative for the fields it carries; the
  // cached view keeps the rest (slug, tags, content date).
  const write = async (call: () => Promise<AssetMetaDetail>) => {
    setBusy(true);
    setError(null);
    try {
      const detail = await call();
      queryClient.setQueryData<AssetMetaView>(qk.assetMeta(asset.slug), (old) =>
        old ? { ...old, ...detail } : old,
      );
      setDraft(null);
      await onChanged();
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  };

  const onDialogSaved = async (detail: AssetMetaDetail | null, tags: string[] | undefined) => {
    queryClient.setQueryData<AssetMetaView>(qk.assetMeta(asset.slug), (old) =>
      old ? { ...old, ...detail, ...(tags ? { tags } : {}) } : old,
    );
    setDialogOpen(false);
    await onChanged();
  };

  const saveSummary = () => {
    if (draft === null) return;
    const summary = draft.trim() || null;
    if (summary === meta.summary) {
      setDraft(null);
      return;
    }
    void write(() => api.patchMeta(asset.id, { summary }));
  };

  const maintainer = meta.maintainer
    ? meta.maintainer.display_name || meta.maintainer.email
    : null;
  const changed = formatDateTime(meta.content_updated_at);

  return (
    <PanelSection title={t("assetMeta.title")}>
      {draft !== null ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            saveSummary();
          }}
        >
          <textarea
            autoFocus
            aria-label={t("assetMeta.summaryLabel")}
            value={draft}
            maxLength={SUMMARY_MAX}
            rows={4}
            onChange={(e) => setDraft(e.target.value)}
            className={clsx(TEXTAREA_CLASS, "w-full")}
          />
          <div className="flex justify-end gap-2 mt-1">
            <button
              type="button"
              onClick={() => setDraft(null)}
              className="text-meta text-text-tertiary hover:text-text-primary px-2 py-1"
            >
              {t("common.cancel")}
            </button>
            <button
              type="submit"
              disabled={busy}
              className="text-meta font-medium text-accent hover:underline px-2 py-1 disabled:opacity-50"
            >
              {busy ? t("common.saving") : t("common.save")}
            </button>
          </div>
        </form>
      ) : meta.summary ? (
        <p className="text-ui text-text-secondary whitespace-pre-line break-words">{meta.summary}</p>
      ) : (
        !editor && <p className="text-meta text-text-tertiary">{t("assetMeta.noSummary")}</p>
      )}

      {(meta.doc_type || meta.freshness !== "current" || meta.summary) && (
        <div className="flex flex-wrap items-center gap-1.5 mt-2">
          {meta.doc_type && (
            <DocTypeBadge docType={meta.doc_type} />
          )}
          <FreshnessBadge freshness={meta.freshness} />
          {meta.summary && meta.summary_source === "agent" && (
            <span className="text-meta px-2 py-0.5 rounded-full bg-info/12 text-info">
              {t("assetMeta.byAgent")}
            </span>
          )}
          {meta.summary && meta.flags.includes("summary_stale") && (
            <span
              className="text-meta px-2 py-0.5 rounded-full bg-warning/15 text-warning"
              title={t("assetMeta.staleTitle")}
            >
              {t("assetMeta.stale")}
            </span>
          )}
        </div>
      )}

      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-meta">
        {maintainer && (
          <>
            <dt className="text-text-tertiary">{t("assetMeta.maintainer")}</dt>
            <dd className="text-text-secondary truncate">{maintainer}</dd>
          </>
        )}
        {changed && (
          <>
            <dt className="text-text-tertiary">{t("assetMeta.changed")}</dt>
            <dd className="text-text-secondary">
              <time dateTime={meta.content_updated_at ?? undefined}>{changed}</time>
            </dd>
          </>
        )}
        {meta.review_due_at && (
          <>
            <dt className="text-text-tertiary">{t("assetMeta.reviewDue")}</dt>
            <dd className={meta.freshness === "review_overdue" ? "text-warning" : "text-text-secondary"}>
              <time dateTime={meta.review_due_at}>{formatDay(meta.review_due_at)}</time>
            </dd>
          </>
        )}
      </dl>

      {error && <p className="mt-2 text-meta text-danger">{error}</p>}

      {editor && draft === null && (
        <div className="flex flex-col gap-0.5 -mx-2 mt-1">
          <PanelAction
            icon={meta.summary ? <Pencil size={14} aria-hidden /> : <Plus size={14} aria-hidden />}
            label={meta.summary ? t("assetMeta.editSummary") : t("assetMeta.addSummary")}
            title={meta.summary ? t("assetMeta.editSummary") : t("assetMeta.addSummary")}
            onClick={() => setDraft(meta.summary ?? "")}
          />
          <PanelAction
            icon={<SlidersHorizontal size={14} aria-hidden />}
            label={t("assetMeta.editMeta")}
            title={t("assetMeta.editMeta")}
            onClick={() => setDialogOpen(true)}
          />
          {meta.freshness === "review_overdue" && (
            <PanelAction
              icon={<CheckCircle2 size={14} aria-hidden />}
              label={t("assetMeta.stillCurrent")}
              title={t("assetMeta.stillCurrentTitle")}
              disabled={busy}
              onClick={() => void write(() => api.markReviewed(asset.id))}
            />
          )}
        </div>
      )}
      {dialogOpen && (
        <AssetMetaDialog
          assetId={asset.id}
          meta={meta}
          people={peopleFor(meta, asset)}
          onClose={() => setDialogOpen(false)}
          onSaved={(detail, tags) => void onDialogSaved(detail, tags)}
        />
      )}
    </PanelSection>
  );
}

/** Maintainer candidates known here: the current maintainer and the owner. */
function peopleFor(meta: AssetMetaView, asset: AssetSummary): Person[] {
  const people = new Map<string, string>();
  const add = (p: { id: string; email: string | null; display_name: string | null } | null | undefined) => {
    if (p) people.set(p.id, p.display_name || p.email || p.id);
  };
  add(meta.maintainer);
  add(asset.owner);
  return [...people].map(([id, label]) => ({ id, label }));
}
