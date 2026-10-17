import { FormEvent, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, AssetSummary } from "../api";
import { formatApiError } from "../lib/apiError";
import { t } from "../lib/i18n";
import { projectListQuery } from "../lib/queries";
import { useToast } from "./Toast";
import { Dialog } from "./ui/Dialog";
import { ProjectPicker } from "./projects/ProjectPicker";
import { Button } from "./ui/Button";

interface Props {
  asset: AssetSummary;
  onClose: () => void;
  onUpdated: () => void;
}

/** Assign an asset to a project or take it out of one: an access decision,
 * kept separate from uploading a new version. */
export function MoveToProjectDialog({ asset, onClose, onUpdated }: Props) {
  const list = useQuery(projectListQuery);
  // Only projects the caller can add files to; a failed load reads as none.
  const projects = useMemo(
    () =>
      list.isPending ? null : (list.data ?? []).filter((p) => p.my_role === "owner" || p.my_role === "editor"),
    [list.isPending, list.data],
  );
  const [projectId, setProjectId] = useState<string>(asset.project_id ?? "");
  const [saving, setSaving] = useState(false);
  const { toast } = useToast();
  const unchanged = projectId === (asset.project_id ?? "");

  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (unchanged || saving) return;
    setSaving(true);
    try {
      await api.patchAssetProject(asset.slug, projectId || null);
      toast(projectId ? t("moveToProject.assigned") : t("moveToProject.unassigned"), "success");
      onUpdated();
      onClose();
    } catch (err) {
      toast(formatApiError(err), "error");
      setSaving(false);
    }
  };

  return (
    <Dialog eyebrow={t("common.project")} title={asset.title || asset.slug} onClose={onClose} maxWidth="lg">
      <form onSubmit={save} className="space-y-4 px-5 py-5 sm:px-6">
        <p className="text-ui text-text-secondary">{t("moveToProject.intro")}</p>
        {projects === null ? (
          <p className="text-ui text-text-secondary">{t("common.loading")}</p>
        ) : projects.length === 0 ? (
          <p className="text-ui text-text-secondary">{t("moveToProject.none")}</p>
        ) : (
          <ProjectPicker
            projects={projects}
            value={projectId}
            onChange={setProjectId}
            label={t("common.project")}
            noneLabel={t("moveToProject.noProject")}
            disabled={saving}
          />
        )}
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="ghost" onClick={onClose} disabled={saving}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" busy={saving} disabled={unchanged}>
            {t("common.save")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
