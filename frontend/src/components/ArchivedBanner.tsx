import { Archive } from "lucide-react";
import { formatDay } from "../lib/format";
import { t } from "../lib/i18n";

interface Props {
  archivedAt: string;
  /** Brings the document back from the archive; only for its managers. */
  onUnarchive?: () => void;
}

/**
 * "This document is in the archive" above the reader, in the same flow and
 * style as the other reader banners (`SupersededBanner`). It stays: the
 * archive is a state of the document, not a notice to dismiss.
 */
export function ArchivedBanner({ archivedAt, onUnarchive }: Props) {
  const date = Number.isNaN(Date.parse(archivedAt)) ? null : formatDay(archivedAt);
  return (
    <div role="status" className="border-b border-border bg-surface-subtle px-(--gutter) py-2.5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-ui">
        <Archive size={16} className="shrink-0 text-text-secondary" aria-hidden />
        <p className="min-w-0 flex-1 text-text-primary">
          {date ? t("archive.banner", { date }) : t("archive.bannerUndated")}
        </p>
        {onUnarchive && (
          <button
            type="button"
            onClick={onUnarchive}
            className="shrink-0 rounded-control px-2 py-0.5 font-medium text-accent hover:bg-accent/10 focus-visible:outline-2 focus-visible:outline-accent"
          >
            {t("assetMenu.unarchive")}
          </button>
        )}
      </div>
    </div>
  );
}
