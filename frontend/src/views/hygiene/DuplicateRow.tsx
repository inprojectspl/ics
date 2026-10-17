import { memo, useState } from "react";

import { api, type DuplicatePair } from "../../api";
import { Button } from "../../components/ui/Button";
import { formatApiError } from "../../lib/apiError";
import { formatNumber, t } from "../../lib/i18n";

interface Props {
  slug: string;
  pair: DuplicatePair;
  onDone: (message: string) => void;
  onError: (message: string) => void;
}

/** A suggested pair of duplicate documents: accept it as a relation or dismiss it. */
export const DuplicateRow = memo(function DuplicateRow({ slug, pair, onDone, onError }: Props) {
  const [busy, setBusy] = useState(false);
  const { a, b } = pair;

  const run = async (write: () => Promise<unknown>, message: string) => {
    setBusy(true);
    try {
      await write();
      onDone(message);
    } catch (e) {
      onError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className="border border-border rounded-control bg-surface px-4 py-3 flex flex-wrap items-center gap-x-3 gap-y-2">
      <div className="flex-1 min-w-[12rem]">
        <a href={`/v/${a.slug}`} className="font-medium text-text-primary hover:text-accent break-words">
          {a.title || a.slug}
        </a>
        <span className="mx-2 text-text-tertiary" aria-hidden>
          ↔
        </span>
        <a href={`/v/${b.slug}`} className="font-medium text-text-primary hover:text-accent break-words">
          {b.title || b.slug}
        </a>
        <p className="text-meta text-text-tertiary">
          {t(pair.certainty === "certain" ? "hygiene.duplicateCertain" : "hygiene.duplicateCandidate", {
            similarity: formatNumber(pair.similarity, { style: "percent" }),
          })}
        </p>
      </div>
      <Button
        size="sm"
        variant="secondary"
        disabled={busy}
        onClick={() => void run(() => api.markDuplicate(slug, a.id, b.id), t("hygiene.duplicateMarked"))}
      >
        {t("hygiene.markDuplicate")}
      </Button>
      <Button
        size="sm"
        variant="ghost"
        disabled={busy}
        onClick={() => void run(() => api.dismissDuplicate(slug, a.id, b.id), t("hygiene.duplicateDismissed"))}
      >
        {t("hygiene.notDuplicate")}
      </Button>
    </li>
  );
});
