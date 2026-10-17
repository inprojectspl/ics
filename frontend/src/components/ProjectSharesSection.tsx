import { FormEvent, useState } from "react";
import { clsx } from "clsx";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import {
  api,
  type AssetSummary,
  type ProjectShareRole,
  type ProjectShareRow,
  type ProjectSummary,
} from "../api";
import { formatApiError } from "../lib/apiError";
import { t } from "../lib/i18n";
import { qk, projectListQuery } from "../lib/queries";
import { AccessList, AccessRow } from "./share/AccessRow";
import { AppLink } from "./ui/AppLink";
import { Badge } from "./ui/Badge";
import { ProjectPicker } from "./projects/ProjectPicker";
import { Button } from "./ui/Button";
import { INPUT_CLASS } from "./Field";

interface Props {
  asset: AssetSummary;
}

const NO_PROJECTS: ProjectSummary[] = [];

/**
 * Assigns the document to projects besides its home one (ADR-0017). Members
 * of an assigned project see it with the chosen role. Only projects where
 * the caller may add content are offered, as the backend requires.
 */
export function ProjectSharesSection({ asset }: Props) {
  const queryClient = useQueryClient();
  const sharesQuery = useQuery({
    queryKey: qk.projectShares(asset.id),
    queryFn: () => api.listProjectShares(asset.id),
  });
  const projectsQuery = useQuery({
    ...projectListQuery,
  });
  const [projectId, setProjectId] = useState("");
  const [role, setRole] = useState<ProjectShareRole>("viewer");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const shares = sharesQuery.data ?? null;
  const assigned = new Set(shares?.map((s) => s.project_id));
  const candidates = (projectsQuery.data ?? NO_PROJECTS).filter(
    (p) =>
      (p.my_role === "owner" || p.my_role === "editor") &&
      p.id !== asset.project_id &&
      !assigned.has(p.id),
  );
  // The pick falls back to the first candidate, so no effect has to reset it
  // when the list changes.
  const noCandidates = projectsQuery.isSuccess && candidates.length === 0;
  const picked = candidates.some((p) => p.id === projectId) ? projectId : (candidates[0]?.id ?? "");

  const apply = async (call: () => Promise<ProjectShareRow[]>) => {
    setBusy(true);
    setError(null);
    try {
      const next = await call();
      queryClient.setQueryData(qk.projectShares(asset.id), next);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  };

  const onAdd = (e: FormEvent) => {
    e.preventDefault();
    if (!picked || busy) return;
    void apply(() => api.putProjectShare(asset.id, picked, role));
  };

  return (
    <section className="space-y-4">
      <p className="text-ui text-text-secondary">{t("projectShares.intro")}</p>

      {candidates.length > 0 ? (
        <form onSubmit={onAdd} className="space-y-3">
          <ProjectPicker projects={candidates} value={picked} onChange={setProjectId} label={t("common.project")} />
          <div className="flex flex-wrap items-end gap-2">
            <label className="w-40">
              <span className="mb-1.5 block text-ui font-medium text-text-primary">{t("common.role")}</span>
              <select value={role} onChange={(e) => setRole(e.target.value as ProjectShareRole)} className={INPUT_CLASS}>
                <option value="viewer">{t("shareDialog.roleViewer")}</option>
                <option value="editor">{t("shareDialog.roleEditor")}</option>
              </select>
            </label>
            <Button type="submit" busy={busy}>
              {t("common.add")}
            </Button>
          </div>
        </form>
      ) : null}

      {error && <p className="text-ui text-danger mb-3">{error}</p>}

      {shares === null ? (
        sharesQuery.isError ? null : <p className="text-meta text-text-secondary">{t("common.loading")}</p>
      ) : shares.length === 0 ? (
        // With nothing to add either, the note below says it all.
        noCandidates ? null : <p className="text-meta text-text-secondary">{t("projectShares.none")}</p>
      ) : (
        <AccessList label={t("projectShares.listLabel")}>
          {shares.map((s) => (
            <AccessRow
              key={s.project_id}
              title={
                <AppLink href={`/projects/${s.project_slug}`} className="hover:text-accent">
                  {s.project_name}
                </AppLink>
              }
              badge={<Badge tone={s.role === "editor" ? "accent" : "neutral"}>{t(s.role === "editor" ? "shareDialog.roleEditor" : "shareDialog.roleViewer")}</Badge>}
              actions={
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={busy}
                  aria-label={t("projectShares.removeLabel", { name: s.project_name })}
                  onClick={() => void apply(() => api.deleteProjectShare(asset.id, s.project_id))}
                >
                  {t("projectShares.remove")}
                </Button>
              }
            />
          ))}
        </AccessList>
      )}

      {noCandidates && shares !== null && (
        <p className={clsx("text-meta text-text-secondary", shares.length > 0 && "mt-3")}>
          {shares.length > 0 ? t("projectShares.noMoreCandidates") : t("projectShares.noCandidates")}
        </p>
      )}
    </section>
  );
}
