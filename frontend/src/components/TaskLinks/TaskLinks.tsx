import { useCallback, useState } from "react";
import { ExternalLink, X } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type ExternalRef } from "../../api";
import { ApiError } from "../../api/_core";
import { formatApiError } from "../../lib/apiError";
import { t } from "../../lib/i18n";
import { qk } from "../../lib/queries";
import { Button } from "../ui/Button";
import { LinkTaskDialog } from "./LinkTaskDialog";
import { ROLE_LABEL, refNumber, safeUrl } from "./taskRef";

interface Props {
  assetId: string;
  slug: string;
  canEdit: boolean;
}

/**
 * "Used in tasks": work packages and PS nodes that link this document
 * (ADR-0018). Labels come from other systems and are rendered as text only.
 */
export function TaskLinks({ assetId, slug, canEdit }: Props) {
  const queryClient = useQueryClient();
  const key = qk.externalRefs(assetId);
  const { data, error } = useQuery({
    queryKey: key,
    queryFn: () => api.listExternalRefs(assetId),
    retry: false,
  });
  const [linking, setLinking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const refresh = useCallback(
    () => queryClient.invalidateQueries({ queryKey: qk.externalRefs(assetId) }),
    [queryClient, assetId],
  );

  const remove = async (ref: ExternalRef) => {
    setBusy(true);
    setActionError(null);
    try {
      await api.deleteExternalRef(ref.id);
      queryClient.setQueryData<ExternalRef[]>(key, (old) => old?.filter((r) => r.id !== ref.id));
    } catch (e) {
      setActionError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  };

  // No graph access: the section does not exist for this viewer.
  if (error instanceof ApiError && error.status === 404) return null;

  return (
    <section className="mt-4" aria-labelledby={`task-links-${assetId}`}>
      <h4
        id={`task-links-${assetId}`}
        className="text-meta text-text-secondary mb-1 font-medium"
      >
        {t("taskLinks.title")}
      </h4>
      {error && <p className="text-meta text-danger">{formatApiError(error)}</p>}
      {data && data.length === 0 && <p className="text-meta text-text-tertiary">{t("taskLinks.none")}</p>}
      {data && data.length > 0 && (
        <ul>
          {data.map((ref) => {
            const url = safeUrl(ref.url);
            const number = refNumber(ref);
            return (
              <li key={ref.id} className="py-1.5 border-b border-border last:border-b-0 flex items-start gap-2">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5 flex-wrap text-ui">
                    {url ? (
                      <a
                        href={url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 font-code text-accent hover:underline"
                      >
                        {number}
                        <ExternalLink size={12} aria-hidden />
                      </a>
                    ) : (
                      <span className="font-code text-text-primary">{number}</span>
                    )}
                    {ref.label && <span className="text-text-primary truncate">{ref.label}</span>}
                  </div>
                  <div className="flex items-center gap-1.5 flex-wrap mt-0.5 text-meta">
                    {ref.role === "deliverable" ? (
                      <span className="px-1.5 rounded-full bg-accent/10 text-accent">
                        {t("taskLinks.roleDeliverable")}
                      </span>
                    ) : (
                      <span className="text-text-tertiary">{t(ROLE_LABEL[ref.role])}</span>
                    )}
                    {ref.required && (
                      <span className="px-1.5 rounded-full bg-warning/15 text-warning">{t("taskLinks.required")}</span>
                    )}
                    {ref.asset_path && <span className="font-code text-text-tertiary">{ref.asset_path}</span>}
                    {ref.basis_changed && ref.pinned_version !== null && (
                      <span className="text-warning">{t("taskLinks.pinnedChanged", { version: ref.pinned_version })}</span>
                    )}
                  </div>
                  {ref.note && <p className="text-meta text-text-secondary mt-0.5">{ref.note}</p>}
                </div>
                {canEdit && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void remove(ref)}
                    aria-label={t("taskLinks.removeLabel", { task: number })}
                    className="shrink-0 p-1 rounded-control text-text-tertiary hover:text-danger hover:bg-danger/10 disabled:opacity-50"
                  >
                    <X size={14} aria-hidden />
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {actionError && <p className="text-meta text-danger mt-1">{actionError}</p>}
      {data && canEdit && (
        <div className="mt-2">
          <Button size="sm" variant="secondary" onClick={() => setLinking(true)}>
            {t("taskLinks.link")}
          </Button>
        </div>
      )}
      {linking && (
        <LinkTaskDialog
          assetId={assetId}
          slug={slug}
          onClose={() => setLinking(false)}
          onLinked={() => {
            setLinking(false);
            void refresh();
          }}
        />
      )}
    </section>
  );
}
