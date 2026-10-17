import { useCallback, useEffect, useMemo, useState } from "react";
import { clsx } from "clsx";
import { api, AssetSummary, DiffSummary, VersionRow } from "../api";
import { formatApiError } from "../lib/apiError";
import { t } from "../lib/i18n";
import { navigate } from "../lib/navigate";
import { useConfirm } from "./ConfirmDialog";
import { Dialog } from "./ui/Dialog";
import { VersionDiffSummary } from "./VersionDiffSummary";
import { VersionHistoryList } from "./VersionHistoryList";
import { VersionPicker } from "./VersionPicker";

interface Props {
  asset: AssetSummary;
  onClose: () => void;
  onRestored: () => void;
}

type Tab = "list" | "compare";

export function VersionsDialog({ asset, onClose, onRestored }: Props) {
  const [versions, setVersions] = useState<VersionRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [tab, setTab] = useState<Tab>("list");
  const confirm = useConfirm();

  const refresh = useCallback(
    () =>
      api.listVersions(asset.id).then(setVersions, (e) => setError(formatApiError(e))),
    [asset.id],
  );

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const restore = async (n: number) => {
    const ok = await confirm({
      title: t("versionsDialog.restoreTitle", { version: n }),
      message: t("versionsDialog.restoreMessage", { version: n }),
      confirmLabel: t("versionsDialog.restore"),
    });
    if (!ok) return;
    setBusy(n);
    setError(null);
    try {
      await api.restoreVersion(asset.id, n);
      await refresh();
      onRestored();
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(null);
    }
  };

  // Preview is separate from restore: it opens `/v/<slug>?ver=N` read-only
  // without bumping the asset version.
  const preview = (n: number) => {
    onClose();
    navigate(`/v/${asset.slug}?ver=${n}`);
  };

  // Restoring requires editor or higher. History and preview are viewer-level,
  // so without this a read-only collaborator would see a restore button that 404s.
  const canRestore = asset.my_role !== "viewer";

  // HTML bundles are comparable too (text files get a full diff, binary files
  // an entry without content).
  const canCompare = versions != null && versions.length >= 2;

  return (
    <Dialog eyebrow={t("versionsDialog.eyebrow")} title={asset.title || asset.slug} onClose={onClose} maxWidth="2xl">
      {canCompare && (
        <nav className="px-6 pt-4 border-b border-border flex gap-6">
          <TabButton active={tab === "list"} onClick={() => setTab("list")}>
            {t("versionsDialog.tabHistory")}
          </TabButton>
          <TabButton active={tab === "compare"} onClick={() => setTab("compare")}>
            {t("versionsDialog.tabCompare")}
          </TabButton>
        </nav>
      )}
      <section className="px-6 py-5">
        {error && <p className="text-ui text-danger mb-4">{error}</p>}
        {tab === "list" ? (
          <VersionHistoryList
            versions={versions}
            renderActions={(v) => (
              <>
                <button
                  onClick={() => preview(v.version)}
                  className="text-ui text-text-secondary hover:text-accent hover:underline"
                >
                  {v.is_current ? t("common.open") : t("common.view")}
                </button>
                {!v.is_current && canRestore && (
                  <button
                    onClick={() => restore(v.version)}
                    disabled={busy !== null}
                    className={clsx(
                      "text-ui text-accent hover:underline",
                      "disabled:opacity-50 disabled:no-underline",
                    )}
                  >
                    {busy === v.version ? t("versionsDialog.restoring") : t("versionsDialog.restore")}
                  </button>
                )}
              </>
            )}
          />
        ) : (
          <CompareView
            asset={asset}
            versions={versions ?? []}
          />
        )}
      </section>
    </Dialog>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={clsx(
        "pb-3 -mb-px border-b-2 text-ui transition-colors",
        active
          ? "border-accent text-text-primary font-medium"
          : "border-transparent text-text-tertiary hover:text-text-secondary",
      )}
    >
      {children}
    </button>
  );
}

type DiffResult = { key: string; summary?: DiffSummary; error?: string };

function CompareView({
  asset,
  versions,
}: {
  asset: AssetSummary;
  versions: VersionRow[];
}) {
  // Default: compare second-most-recent -> current (typical "what just
  // changed?" question).
  const sorted = useMemo(
    () => [...versions].sort((a, b) => a.version - b.version),
    [versions],
  );
  const latest = sorted[sorted.length - 1]?.version ?? 1;
  const previous = sorted[sorted.length - 2]?.version ?? 1;

  const [fromV, setFromV] = useState<number>(previous);
  const [toV, setToV] = useState<number>(latest);
  // The result remembers which pair it belongs to, so picking another pair
  // hides the previous diff (and error) without a reset effect.
  const pairKey = fromV === toV ? null : `${asset.id}:${fromV}:${toV}`;
  const [result, setResult] = useState<DiffResult | null>(null);
  const current = result && result.key === pairKey ? result : null;
  const loading = pairKey !== null && !current;
  const summary = current?.summary ?? null;
  const error = current?.error ?? null;

  useEffect(() => {
    if (pairKey === null) return;
    let cancelled = false;
    api.diffVersions(asset.id, fromV, toV).then(
      (d) => {
        if (!cancelled) setResult({ key: pairKey, summary: d });
      },
      (e) => {
        if (!cancelled) setResult({ key: pairKey, error: formatApiError(e) });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [asset.id, fromV, toV, pairKey]);

  return (
    <div className="space-y-4">
      <VersionPicker
        versions={sorted}
        fromV={fromV}
        toV={toV}
        onChange={({ fromV: f, toV: to }) => {
          setFromV(f);
          setToV(to);
        }}
        aside={
          <button
            type="button"
            onClick={() => navigate(`/v/${asset.slug}/diff?from=${fromV}&to=${toV}`)}
            className="text-ui text-accent hover:underline"
          >
            {t("versionsDialog.fullScreen")}
          </button>
        }
      />

      {fromV === toV && (
        <p className="text-meta text-text-tertiary">
          {t("error.same_version")}
        </p>
      )}

      {loading && <p className="text-text-tertiary text-meta">{t("versionsDialog.computing")}</p>}
      {error && <p className="text-ui text-danger">{error}</p>}

      {summary && !loading && (
        <>
          {/* The modal is a summary with just the list of changes. File contents
              expand on the comparison screen, which has room for them. */}
          <VersionDiffSummary files={summary.files} />
          <p className="text-meta text-text-tertiary">
            {t("versionsDialog.fullScreenHint")}
          </p>
        </>
      )}
    </div>
  );
}
