import { useState } from "react";
import { ArrowUpRight, Download } from "lucide-react";
import { SecurityReport, SecurityStatus } from "../api";
import { formatApiError } from "../lib/apiError";
import { formatBytes } from "../lib/format";
import { t } from "../lib/i18n";
import { mt } from "../styles/markdown-theme";
import { BundleFileTree } from "./BundleFileTree";
import { Button, buttonClass } from "./ui/Button";
import { SecurityFindings } from "./SecurityFindings";
import { WithheldNotice } from "./ViewerStates";

interface Props {
  title: string | null;
  meta?: string | null;
  sizeBytes?: number | null;
  entryPath?: string | null;
  /** Relative paths inside the bundle; undefined for share visitors, who
   * must not get a directory listing. */
  files?: string[] | null;
  securityStatus?: SecurityStatus | null;
  securityReport?: SecurityReport | null;
  securityBypass?: boolean;
  /** Visitor-side gate: replaces the open buttons with a "pending review"
   * notice. */
  accessGated?: boolean;
  /** Fetches the signed cross-origin URL to navigate to. Called on click,
   * not on mount, so the short-lived signature does not expire meanwhile. */
  fetchGrantUrl: () => Promise<string>;
  /** When provided, renders a "download source (ZIP)" button alongside
   * the open buttons. The href points at the owner or share download
   * endpoint depending on the caller. */
  downloadHref?: string;
  /**
   * Number of the archived version being previewed; changes the button copy.
   * The caller decides whether to hide `downloadHref` (the ZIP always packs
   * the current version), so that policy stays in one place per view.
   */
  previewVersion?: number | null;
}

/**
 * Landing card for html_bundle assets. The bundle is served from a separate
 * origin; opening it goes through a backend grant endpoint that sets a scoped
 * cookie on that origin, then navigates there in full viewport.
 */
export function HtmlBundleView({
  title,
  meta,
  sizeBytes,
  entryPath,
  files,
  securityStatus,
  securityReport,
  securityBypass,
  accessGated = false,
  fetchGrantUrl,
  downloadHref,
  previewVersion = null,
}: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const open = async (newTab: boolean) => {
    setError(null);
    setBusy(true);
    try {
      const url = await fetchGrantUrl();
      if (newTab) {
        window.open(url, "_blank", "noopener,noreferrer");
      } else {
        window.location.href = url;
      }
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <article className="max-w-(--reading-width) mx-auto px-(--gutter) py-16">
      {meta && <div className={mt.meta}>{meta}</div>}
      {title && <h1 className={mt.title}>{title}</h1>}

      <p className="text-text-secondary text-body mb-8 mt-4">
        {t("htmlBundleView.intro")}
        {previewVersion != null && (
          <>
            {" "}
            {t("htmlBundleView.previewBefore")}{" "}
            <strong>{t("htmlBundleView.previewVersion", { version: previewVersion })}</strong>
            {t("htmlBundleView.previewAfter")}
          </>
        )}
      </p>

      <SecurityFindings
        status={securityStatus}
        report={securityReport}
        bypassed={securityBypass}
      />

      {accessGated ? (
        <WithheldNotice className="mb-10" />
      ) : (
        <div className="flex flex-wrap items-center gap-3 mb-10">
          <Button size="lg" onClick={() => open(false)} busy={busy} trailingIcon={<ArrowUpRight size={16} aria-hidden />}>
            {busy
              ? t("htmlBundleView.opening")
              : previewVersion != null
                ? t("htmlBundleView.openPreview", { version: previewVersion })
                : t("htmlBundleView.openFullscreen")}
          </Button>
          <Button variant="secondary" size="lg" onClick={() => open(true)} disabled={busy}>
            {t("htmlBundleView.openNewTab")}
          </Button>
          {downloadHref && (
            <a
              href={downloadHref}
              download
              aria-label={t("htmlBundleView.downloadZip")}
              title={t("htmlBundleView.downloadZipTitle")}
              className={buttonClass("secondary", "lg")}
            >
              <Download size={16} aria-hidden />
              {t("htmlBundleView.downloadZip")}
            </a>
          )}
        </div>
      )}

      {error && <p className="text-ui text-danger mb-6">{error}</p>}

      <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-ui mb-8">
        {entryPath && (
          <>
            <dt className="text-meta text-text-secondary font-medium">
              {t("htmlBundleView.entryPoint")}
            </dt>
            <dd className="font-code text-text-secondary">{entryPath}</dd>
          </>
        )}
        {sizeBytes != null && (
          <>
            <dt className="text-meta text-text-secondary font-medium">
              {t("htmlBundleView.size")}
            </dt>
            <dd className="font-code text-text-secondary">{formatBytes(sizeBytes)}</dd>
          </>
        )}
      </dl>

      {files && files.length > 0 && (
        <BundleFileTree files={files} entryPath={entryPath ?? null} />
      )}

      <p className="text-meta text-text-tertiary mt-12">
        {t("htmlBundleView.back")}
      </p>
    </article>
  );
}

