import { useState } from "react";
import { AlertTriangle, X } from "lucide-react";
import { formatDateTime } from "../lib/format";
import { t } from "../lib/i18n";

interface Props {
  /** Number of the (archived) version being previewed. */
  previewVersion: number;
  currentVersion: number;
  /** ISO creation date of the previewed version, optional. */
  versionCreatedAt?: string | null;
  /** ISO creation date of the current version (its history row). */
  currentCreatedAt?: string | null;
  /** Returns to the current version (drops `?ver=` from the URL). */
  onBackToCurrent: () => void;
}

/**
 * "You are viewing an outdated version" banner above the document content.
 * HTML bundles get an equivalent injected by `app/services/version_banner.py`.
 * In normal flow with no `z-index`, so it scrolls under the sticky chrome
 * instead of sliding over the navbar.
 */
export function StaleVersionNotice({
  previewVersion,
  currentVersion,
  versionCreatedAt,
  currentCreatedAt,
  onBackToCurrent,
}: Props) {
  const [hidden, setHidden] = useState(false);
  if (hidden) return null;

  const previewWhen = formatDateTime(versionCreatedAt);
  const currentWhen = formatDateTime(currentCreatedAt);

  return (
    <div
      role="alert"
      className="relative border-b border-danger/40 bg-danger/10 px-(--gutter) py-2.5"
    >
      <div className="flex items-start gap-3 pr-8 text-ui">
        <AlertTriangle size={16} className="mt-0.5 shrink-0 text-danger" aria-hidden />
        <p className="text-text-primary">
          <span className="font-semibold text-danger">
            {previewWhen
              ? t("staleVersion.titleWithDate", { version: previewVersion, date: previewWhen })
              : t("staleVersion.title", { version: previewVersion })}
          </span>
          :{" "}
          {currentWhen
            ? t("staleVersion.bodyWithDate", { current: currentVersion, date: currentWhen })
            : t("staleVersion.body", { current: currentVersion })}{" "}
          <button
            type="button"
            onClick={onBackToCurrent}
            className="text-accent underline hover:no-underline"
          >
            {t("staleVersion.back")}
          </button>
        </p>
      </div>
      <button
        type="button"
        onClick={() => setHidden(true)}
        aria-label={t("staleVersion.hide")}
        className="absolute top-1.5 right-2 inline-flex h-7 w-7 items-center justify-center rounded-control text-text-tertiary hover:bg-surface-subtle hover:text-text-primary"
      >
        <X size={15} aria-hidden />
      </button>
    </div>
  );
}
