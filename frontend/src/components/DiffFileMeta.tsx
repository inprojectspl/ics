import { clsx } from "clsx";
import type { DiffFileChange } from "../api";
import { formatBytes } from "../lib/format";
import { t } from "../lib/i18n";

/**
 * Change marker and line counters of one compared file, shared by
 * `VersionDiffSummary` and `DiffFileBlock` so both show the same edge cases.
 */

export function ChangeMarker({ change }: { change: DiffFileChange["change"] }) {
  const marker = change === "added" ? "+" : change === "removed" ? "−" : "~";
  const cls =
    change === "added" ? "text-success" : change === "removed" ? "text-danger" : "text-warning";
  return (
    <span aria-hidden className={clsx("font-code text-meta w-3 shrink-0", cls)}>
      {marker}
    </span>
  );
}

export function DiffCounters({ file }: { file: DiffFileChange }) {
  return (
    <span className="ml-auto flex items-center gap-3 shrink-0 font-code text-meta">
      {file.binary ? (
        <span className="text-text-tertiary">
          {t("diffFileMeta.binary")}{file.size_to != null && ` · ${formatBytes(file.size_to)}`}
        </span>
      ) : file.added_lines == null ? (
        // The backend did not count lines (file above the byte threshold),
        // so do not pretend to have a number.
        <span className="text-text-tertiary" title={t("diffFileMeta.tooLarge")}>
          ~
        </span>
      ) : file.added_lines === 0 && file.removed_lines === 0 ? (
        // Bytes differ but lines do not: a line-ending or trailing-whitespace
        // change. "+0 -0" would look broken.
        <span className="text-text-tertiary" title={t("diffFileMeta.outsideLines")}>
          {t("diffFileMeta.noLineChanges")}
        </span>
      ) : (
        <>
          <span className="text-success">+{file.added_lines}</span>
          <span className="text-danger">−{file.removed_lines ?? 0}</span>
        </>
      )}
    </span>
  );
}
