import type { ReactNode } from "react";
import { clsx } from "clsx";
import type { VersionRow } from "../api";
import { formatBytes, formatDateTime } from "../lib/format";
import { t } from "../lib/i18n";

interface Props {
  versions: VersionRow[] | null;
  /** Per-row actions (view / restore). Return `null` to render nothing for
   * a version, e.g. the current one. */
  renderActions: (v: VersionRow) => ReactNode;
}

/**
 * "Who updated the file and when" list, shared by the versions dialog (owner
 * view) and the history section under the document (share page and reader
 * view). Pure presentation: no fetching and no knowledge of what the actions do.
 */
export function VersionHistoryList({ versions, renderActions }: Props) {
  if (versions === null) return <p className="text-text-tertiary text-meta">{t("common.loading")}</p>;
  if (versions.length === 0) return <p className="text-text-tertiary text-meta">{t("versionHistory.empty")}</p>;
  return (
    <ul className="space-y-2">
      {versions.map((v) => (
        <li
          key={v.version}
          className={clsx(
            "rounded-control border p-3 flex items-center justify-between gap-4",
            v.is_current ? "border-accent bg-accent-soft/30" : "border-border",
          )}
        >
          <div className="min-w-0">
            <div className="flex items-baseline gap-2 mb-0.5">
              <span className="font-semibold text-text-primary">v{v.version}</span>
              {v.is_current && (
                <span className="text-meta text-accent font-medium">
                  {t("versionHistory.current")}
                </span>
              )}
            </div>
            <div className="text-meta text-text-tertiary truncate">
              {formatDateTime(v.created_at)}
              {v.author && ` · ${v.author}`}
              {v.size_bytes != null && ` · ${formatBytes(v.size_bytes)}`}
            </div>
            {v.change_note && (
              <p className="mt-1 text-ui text-text-secondary break-words">{v.change_note}</p>
            )}
          </div>
          <div className="flex items-center gap-3 shrink-0">{renderActions(v)}</div>
        </li>
      ))}
    </ul>
  );
}
