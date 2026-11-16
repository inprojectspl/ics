import { useState } from "react";

import type { RelationItem } from "../../api";
import { Button, buttonClass } from "../../components/ui/Button";
import { useConfirmBasis, useRelations } from "../../components/RelationsPanel/useRelations";
import { formatApiError } from "../../lib/apiError";
import { t } from "../../lib/i18n";

interface Props {
  slug: string;
  /** Runs after a basis was confirmed, so the page reloads its counters. */
  onDone: () => void;
  onError: (message: string) => void;
}

/** Bases of a document that changed since it was derived from them. */
export function BasisChanges({ slug, onDone, onError }: Props) {
  const { data, error } = useRelations(slug);
  const confirmBasis = useConfirmBasis(slug);
  const [busy, setBusy] = useState<string | null>(null);

  if (error) return <p className="text-meta text-danger">{formatApiError(error)}</p>;
  if (!data) return <p className="text-meta text-text-tertiary">{t("common.loading")}</p>;
  const items = (data.outgoing.derived_from ?? []).filter((r) => r.target_changed);
  if (items.length === 0) return <p className="text-meta text-text-tertiary">{t("hygiene.noChangedBasis")}</p>;

  const confirm = async (id: string) => {
    setBusy(id);
    try {
      await confirmBasis(id);
      onDone();
    } catch (e) {
      onError(formatApiError(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <ul className="space-y-2" aria-label={t("hygiene.changedBases")}>
      {items.map((r) => (
        <li key={r.id} className="flex flex-wrap items-center gap-2 text-ui">
          <span className="flex-1 min-w-[10rem] text-text-primary truncate">{r.other.title || r.other.slug}</span>
          {r.target_version != null && r.target_version_now != null && <BasisLink row={r} />}
          <Button size="sm" variant="ghost" disabled={busy !== null} onClick={() => void confirm(r.id)}>
            {t("assetMeta.stillCurrent")}
          </Button>
        </li>
      ))}
    </ul>
  );
}

/** What changed in the basis; an app's comparison is its publishers', so a
 * document that links to an app opens the app instead. */
function BasisLink({ row: r }: { row: RelationItem }) {
  const app = r.other.kind === "micro_application";
  const href = app ? `/v/${r.other.slug}` : `/v/${r.other.slug}/diff?from=${r.target_version}&to=${r.target_version_now}`;
  return (
    <a href={href} className={buttonClass("secondary", "sm")}>
      {t(app ? "common.open" : "hygiene.showChanges")}
    </a>
  );
}
