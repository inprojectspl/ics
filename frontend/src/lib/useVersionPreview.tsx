/**
 * Read-only archived version preview (ADR-0004), shared by `Viewer` and
 * `ShareView`, which differ only in base URL and history source. Returns
 * ready elements (`staleNotice`, `historySection`) so the views cannot drift.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import type { AssetDoc, VersionRow } from "../api";
import { StaleVersionNotice } from "../components/StaleVersionNotice";
import { SupersededBanner } from "../components/SupersededBanner";
import { VersionHistorySection } from "../components/VersionHistorySection";
import { formatMeta } from "./format";
import { navigate } from "./navigate";

export interface UseVersionPreviewOpts {
  /** The document, or `null` until it loads. */
  doc: AssetDoc | null;
  /** Path without the query: `/v/<slug>` or `/s/<token>`. */
  basePath: string;
  /** Loads the version history. Must be stable (useCallback). */
  loadVersions: () => Promise<VersionRow[]>;
  /** Base URL for downloading the source; hidden in preview mode. */
  downloadPath: string;
}

export interface UseVersionPreviewResult {
  /** Archived version being previewed; `null` means the current one. */
  previewVersion: number | null;
  /** The "updated" overline; in preview it dates the version being read. */
  meta: string | null;
  /** `undefined` in preview mode: the ZIP/file always packs the current version. */
  downloadHref: string | undefined;
  /** The outdated-version bar and the superseded-document bar, or `null`
   * when neither applies. */
  staleNotice: React.ReactNode;
  /** Collapsible version history section below the document (link visitors). */
  historySection: React.ReactNode;
  /** The same history as the reader inspector's tab. */
  historyPanel: React.ReactNode;
  /** Open version N (for the current one, drops `?ver=` from the URL). */
  goToVersion: (n: number) => void;
}

export function useVersionPreview({
  doc,
  basePath,
  loadVersions,
  downloadPath,
}: UseVersionPreviewOpts): UseVersionPreviewResult {
  const previewVersion = doc?.preview_version ?? null;
  const currentVersion = doc?.current_version ?? doc?.version ?? 0;

  const goToVersion = useCallback(
    (n: number) => navigate(n === currentVersion ? basePath : `${basePath}?ver=${n}`),
    [basePath, currentVersion],
  );

  // The notice dates the current version by its history row, as the version
  // list does: `updated_at` also moves on later row writes (metadata, scans),
  // so it can read a minute later than the list.
  const [currentCreated, setCurrentCreated] = useState<{ version: number; at: string | null } | null>(null);
  useEffect(() => {
    if (!previewVersion) return;
    let cancelled = false;
    loadVersions()
      .then((rows) => {
        if (!cancelled) setCurrentCreated({ version: currentVersion, at: rows.find((r) => r.is_current)?.created_at ?? null });
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [previewVersion, currentVersion, loadVersions]);
  const currentCreatedAt = currentCreated?.version === currentVersion ? currentCreated.at : null;

  const successor = doc?.superseded_by ?? null;
  const staleNotice = useMemo(
    () =>
      previewVersion || successor ? (
        <>
          {previewVersion ? (
            <StaleVersionNotice
              previewVersion={previewVersion}
              currentVersion={currentVersion}
              versionCreatedAt={doc?.version_created_at}
              currentCreatedAt={currentCreatedAt}
              onBackToCurrent={() => goToVersion(currentVersion)}
            />
          ) : null}
          {successor ? <SupersededBanner successor={successor} /> : null}
        </>
      ) : null,
    [
      previewVersion,
      successor,
      currentVersion,
      doc?.version_created_at,
      currentCreatedAt,
      goToVersion,
    ],
  );

  const historySection = useMemo(
    () => (
      <VersionHistorySection
        load={loadVersions}
        onPreview={goToVersion}
        activeVersion={previewVersion}
      />
    ),
    [loadVersions, goToVersion, previewVersion],
  );

  const historyPanel = useMemo(
    () => <VersionHistorySection load={loadVersions} onPreview={goToVersion} activeVersion={previewVersion} panel />,
    [loadVersions, goToVersion, previewVersion],
  );

  return {
    previewVersion,
    // In preview the overline must date the content on screen, not the latest
    // change (`updated_at` belongs to a different version).
    meta: formatMeta(previewVersion ? doc?.version_created_at : doc?.updated_at),
    downloadHref: previewVersion ? undefined : downloadPath,
    staleNotice,
    historySection,
    historyPanel,
    goToVersion,
  };
}
