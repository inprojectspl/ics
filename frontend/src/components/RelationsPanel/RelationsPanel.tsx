import { useCallback, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { api } from "../../api";
import { formatApiError } from "../../lib/apiError";
import { t } from "../../lib/i18n";
import { relationLabelKey } from "../../lib/relationLabels";
import { AddRelationDialog } from "../AddRelationDialog";
import { Button } from "../ui/Button";
import { TaskLinks } from "../TaskLinks";
import { countRelations, groupRelations } from "./groupRelations";
import { RelationRow } from "./RelationRow";
import { invalidateRelations, isHidden, useConfirmBasis, useRelations } from "./useRelations";

interface Props {
  slug: string;
  assetId: string;
  /** Editor of this document: may add, remove and confirm relations. */
  canEdit: boolean;
}

/**
 * Relations of one document (ADR-0016), grouped by type and direction,
 * with the editing actions: the list view of the reader's relations tab
 * and of the `?tab=relations` page.
 */
export function RelationsPanel({ slug, assetId, canEdit }: Props) {
  const queryClient = useQueryClient();
  const { data, error } = useRelations(slug);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const confirmBasis = useConfirmBasis(slug);

  const run = useCallback(async (call: () => Promise<unknown>) => {
    setBusy(true);
    setActionError(null);
    try {
      await call();
    } catch (e) {
      setActionError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }, []);

  const onConfirmCurrent = useCallback((id: string) => void run(() => confirmBasis(id)), [run, confirmBasis]);
  const onRemove = useCallback(
    (id: string) =>
      void run(async () => {
        await api.deleteRelation(id);
        await invalidateRelations(queryClient, slug);
      }),
    [run, queryClient, slug],
  );
  const [adding, setAdding] = useState(false);
  const onAdded = useCallback(() => {
    setAdding(false);
    void invalidateRelations(queryClient, slug);
  }, [queryClient, slug]);

  const groups = useMemo(() => (data ? groupRelations(data) : []), [data]);

  if (isHidden(error)) return null;

  const total = countRelations(groups);

  return (
    <div>
      {error && <p className="text-meta text-danger">{formatApiError(error)}</p>}
      {!data && !error && <p className="text-meta text-text-tertiary">{t("common.loading")}</p>}
      {data && total === 0 && <p className="text-meta text-text-tertiary">{t("relations.none")}</p>}

      {groups.map((g) => (
          <section key={g.key} className="mb-3">
            <h4 className="text-meta text-text-secondary font-medium">
              {t(relationLabelKey(g.type, g.direction))}
              <span className="ml-1.5 font-code normal-case tracking-normal">{g.items.length}</span>
            </h4>
            <ul>
              {g.items.map((item) => (
                <RelationRow
                  key={item.id}
                  item={item}
                  direction={g.direction}
                  canEdit={canEdit}
                  busy={busy}
                  onConfirmCurrent={onConfirmCurrent}
                  onRemove={onRemove}
                />
              ))}
            </ul>
          </section>
      ))}

      {actionError && <p className="text-meta text-danger mb-2">{actionError}</p>}
      {data && canEdit && (
        <Button size="sm" variant="secondary" onClick={() => setAdding(true)}>
          {t("relations.addTitle")}
        </Button>
      )}
      {adding && (
        <AddRelationDialog
          assetId={assetId}
          slug={slug}
          onClose={() => setAdding(false)}
          onAdded={onAdded}
        />
      )}
      {data && <TaskLinks assetId={assetId} slug={slug} canEdit={canEdit} />}
    </div>
  );
}
