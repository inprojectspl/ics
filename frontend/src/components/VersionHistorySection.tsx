import { useEffect, useState } from "react";
import { ChevronDown, History } from "lucide-react";
import { clsx } from "clsx";
import type { VersionRow } from "../api";
import { formatApiError } from "../lib/apiError";
import { versionCountLabel } from "../lib/format";
import { t } from "../lib/i18n";
import { VersionHistoryList } from "./VersionHistoryList";

interface Props {
  /** Where to load the history from: `api.getShareVersions(token)` or
   * `api.listVersions(assetId)`. Must be stable (useCallback). */
  load: () => Promise<VersionRow[]>;
  /** Opens a read-only preview of version N. */
  onPreview: (version: number) => void;
  /** Version currently being previewed; its row gets no actions. */
  activeVersion?: number | null;
  /** Inside the reader inspector: the list itself, always open. */
  panel?: boolean;
}

/**
 * Collapsible version history below the document. One light metadata fetch
 * on mount feeds the count shown while collapsed.
 */
export function VersionHistorySection({ load, onPreview, activeVersion, panel = false }: Props) {
  const [versions, setVersions] = useState<VersionRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    load()
      .then((rows) => !cancelled && setVersions(rows))
      .catch((e) => !cancelled && setError(formatApiError(e)));
    return () => {
      cancelled = true;
    };
  }, [load]);

  // The version count must show on the link page even for single-version
  // files. Hide the section only when there is no history at all (assets
  // from before versioning) or the fetch failed: it is an extra, not part
  // of the document.
  if (error || (versions !== null && versions.length === 0)) return null;

  const count = versions?.length ?? 0;
  const list = (
    <VersionHistoryList
      versions={versions}
      renderActions={(v) =>
        v.version === activeVersion ? (
          <span className="text-meta font-medium text-accent">{t("versionHistory.previewing")}</span>
        ) : (
          <button type="button" onClick={() => onPreview(v.version)} className="text-ui font-medium text-accent hover:underline">
            {v.is_current ? t("versionHistory.openCurrent") : t("versionHistory.viewVersion")}
          </button>
        )
      }
    />
  );
  if (panel) return list;

  return (
    <section className="max-w-(--reading-width) mx-auto px-(--gutter) pb-16">
      <div className="border-t border-border pt-4">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="flex items-center gap-2 text-ui text-text-secondary hover:text-text-primary"
        >
          <History size={15} aria-hidden />
          <span>
            {t("versionHistory.title")}
            {count ? ` · ${versionCountLabel(count)}` : ""}
          </span>
          <ChevronDown
            size={15}
            aria-hidden
            className={clsx("transition-transform", open && "rotate-180")}
          />
        </button>
        {open && <div className="mt-4">{list}</div>}
      </div>
    </section>
  );
}
