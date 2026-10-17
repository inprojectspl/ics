import { memo, useEffect, useMemo, useRef, useState } from "react";
import { clsx } from "clsx";
import type { DiffFileChange } from "../api";
import { formatApiError } from "../lib/apiError";
import { t } from "../lib/i18n";
import { observeOnce } from "../lib/lazyObserve";
import { annotateIntraline, pairForSplit, parseUnifiedDiff } from "../lib/parseUnifiedDiff";
import { ChangeMarker, DiffCounters } from "./DiffFileMeta";
import { SplitDiff } from "./SplitDiff";
import { UnifiedDiff } from "./UnifiedDiff";

interface Props {
  file: DiffFileChange;
  mode: "unified" | "split";
  /** Fetches this file's unified diff (called once, when it scrolls into view). */
  load: (path: string) => Promise<string>;
  /** Highlights the block selected in the tree. */
  active: boolean;
  /** Anchor for scrolling from the tree. */
  anchorId: string;
}

/**
 * One file in the comparison stack. The body is fetched only when the block
 * nears the viewport, so a 50-file collection does not fire 50 requests on
 * entry. `memo` because scrolling changes `active` on one block of dozens.
 */
export const DiffFileBlock = memo(function DiffFileBlock({
  file,
  mode,
  load,
  active,
  anchorId,
}: Props) {
  const ref = useRef<HTMLElement>(null);
  const [visible, setVisible] = useState(false);
  const [diff, setDiff] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (el) observeOnce(el, () => setVisible(true));
  }, []);

  useEffect(() => {
    if (!visible || file.binary) return;
    let cancelled = false;
    load(file.path)
      .then((d) => !cancelled && setDiff(d))
      .catch((e) => !cancelled && setError(formatApiError(e)));
    return () => {
      cancelled = true;
    };
  }, [visible, file.binary, file.path, load]);

  // Parse and highlight once per content, regardless of mode: switching
  // between unified and side-by-side only rearranges the same lines, and the
  // intra-line LCS is the most expensive step.
  const lines = useMemo(
    () => (diff === null ? [] : annotateIntraline(parseUnifiedDiff(diff))),
    [diff],
  );
  const rows = useMemo(() => (mode === "split" ? pairForSplit(lines) : []), [mode, lines]);

  return (
    <section
      ref={ref}
      id={anchorId}
      // `scroll-mt` keeps the block header from hiding under the chrome after a jump from the tree.
      className={clsx("scroll-mt-4 rounded-control border", active ? "border-accent" : "border-border")}
    >
      <header
        className={clsx(
          "flex items-baseline gap-2 px-3 py-2 rounded-t-soft border-b border-border",
          active ? "bg-accent-soft/30" : "bg-surface-subtle/40",
        )}
      >
        <ChangeMarker change={file.change} />
        <span className="font-code text-ui text-text-primary truncate">{file.path}</span>
        <DiffCounters file={file} />
      </header>

      <div className="p-2">
        {file.binary ? (
          <p className="text-text-secondary text-ui px-2 py-3">
            {t("diffFileBlock.binary")}
          </p>
        ) : error ? (
          <p className="text-ui text-danger px-2 py-3">{error}</p>
        ) : diff === null ? (
          <p className="text-meta text-text-tertiary px-2 py-3">{t("diffFileBlock.loading")}</p>
        ) : mode === "split" ? (
          <SplitDiff rows={rows} />
        ) : (
          <UnifiedDiff lines={lines} />
        )}
      </div>
    </section>
  );
});
