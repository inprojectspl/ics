import { useQuery } from "@tanstack/react-query";
import { FolderInput } from "lucide-react";
import { api, type AssetSummary, type ProjectSummary } from "../../api";
import { canManage } from "../../lib/assetRoles";
import { formatBytes, formatDateTime } from "../../lib/format";
import { t } from "../../lib/i18n";
import { qk } from "../../lib/queries";
import { AssetMetaSection } from "../AssetMetaSection";
import { KIND_LABEL } from "../documents/kindIcon";
import { SecurityStatusBadge, ShareStatus } from "../documents/ShareStatus";
import { AppLink } from "../ui/AppLink";
import { PanelAction, PanelSection } from "../ui/PanelSection";

interface Props {
  asset: AssetSummary;
  project: ProjectSummary | null;
  onChanged: () => Promise<void>;
  onAssignProject: (() => void) | null;
}

/**
 * The "Details" tab of the reader inspector: what the document is (its
 * description and metadata), where it lives (project), and the plain
 * facts (kind, version, size, sharing).
 */
export function ReaderDetails({ asset, project, onChanged, onAssignProject }: Props) {
  // Readable only by those who may share the asset.
  const shares = useQuery({
    queryKey: qk.projectShares(asset.id),
    queryFn: () => api.listProjectShares(asset.id),
    enabled: canManage(asset),
  }).data;
  const owner = asset.owner ? asset.owner.display_name || asset.owner.email : null;

  return (
    <div>
      <AssetMetaSection asset={asset} onChanged={onChanged} />

      <PanelSection title={t("common.project")}>
        {project ? (
          <AppLink href={`/projects/${project.slug}`} className="text-ui font-medium text-accent hover:underline">
            {project.name}
          </AppLink>
        ) : (
          <p className="text-ui text-text-secondary">
            {t(asset.project_id ? "assetToolbar.hiddenProject" : "assetToolbar.noProject")}
          </p>
        )}
        {shares && shares.length > 0 && (
          <div className="mt-2">
            <p className="mb-1 text-meta text-text-secondary">{t("projectShares.alsoIn")}</p>
            <ul className="flex flex-wrap gap-1.5">
              {shares.map((s) => (
                <li key={s.project_id}>
                  <AppLink href={`/projects/${s.project_slug}`} className="text-meta text-text-primary underline-offset-2 hover:text-accent hover:underline">
                    {s.project_name}
                  </AppLink>
                </li>
              ))}
            </ul>
          </div>
        )}
        {onAssignProject && canManage(asset) && (
          <div className="-mx-2 mt-1.5">
            <PanelAction
              icon={<FolderInput size={15} aria-hidden />}
              label={t(project ? "assetToolbar.changeProject" : "assetToolbar.assignProject")}
              title={t("assetToolbar.assignProjectTitle")}
              onClick={onAssignProject}
            />
          </div>
        )}
      </PanelSection>

      <PanelSection title={t("reader.facts")} last>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-ui">
          <dt className="text-text-secondary">{t("reader.kind")}</dt>
          <dd className="text-text-primary">{t(KIND_LABEL[asset.kind])}</dd>
          <dt className="text-text-secondary">{t("reader.version")}</dt>
          <dd className="tabular-nums text-text-primary">v{asset.version}</dd>
          <dt className="text-text-secondary">{t("reader.size")}</dt>
          <dd className="tabular-nums text-text-primary">{formatBytes(asset.size_bytes)}</dd>
          {owner && (
            <>
              <dt className="text-text-secondary">{t("reader.owner")}</dt>
              <dd className="truncate text-text-primary">{owner}</dd>
            </>
          )}
          <dt className="text-text-secondary">{t("reader.created")}</dt>
          <dd className="text-text-primary">{formatDateTime(asset.created_at)}</dd>
          <dt className="self-center text-text-secondary">{t("reader.sharing")}</dt>
          <dd className="flex flex-wrap gap-1.5">
            <ShareStatus modes={asset.active_share_modes} />
            <SecurityStatusBadge status={asset.security_status} bypassed={asset.security_bypass} />
          </dd>
        </dl>
      </PanelSection>
    </div>
  );
}
