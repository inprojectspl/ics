import { useCallback, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Network, Star } from "lucide-react";
import { api, type AssetSummary, type EffectiveRole, type ProjectSummary } from "../../api";
import { buildAssetMenuActions } from "../../lib/assetMenuActions";
import { canManage } from "../../lib/assetRoles";
import { t } from "../../lib/i18n";
import { navigate } from "../../lib/navigate";
import { qk, projectListQuery } from "../../lib/queries";
import { togglePin, useAssetActions } from "../../lib/useAssetActions";
import type { MenuAction } from "../ui/menuAction";
import { RenameDialog } from "./RenameDialog";

interface Params {
  slug: string;
  /** Caller's role from the document payload. */
  role: EffectiveRole | undefined;
  /** Archived version in view, `null` for the current one. */
  previewVersion: number | null;
  /** Reloads the document after a change to its content. */
  reload: () => void | Promise<void>;
  /** Source download, when the kind has one. */
  downloadHref?: string;
  /** The relations view link (readers reach relations only through it). */
  relationsHref?: string;
}

export interface ReaderActions {
  /** The asset as its owners and editors see it; `null` for readers and until loaded. */
  asset: AssetSummary | null;
  /** Project of the asset when the caller can see it (breadcrumb, details). */
  project: ProjectSummary | null;
  /** Everything the `…` menu (and the phone sheet) offers, in one order. */
  menu: MenuAction[];
  /** Opens the share dialog; `null` when the caller may not share. */
  share: (() => void) | null;
  /** Dialogs the actions open; render once. */
  dialogs: ReactNode;
  /** After a metadata or project change: refresh the asset and the lists. */
  onChanged: () => Promise<void>;
  /** Opens the project dialog (details panel). */
  assignProject: (() => void) | null;
}

const NO_PROJECTS: ProjectSummary[] = [];

/**
 * Actions on the open document for the reader toolbar, menu and details
 * panel. Owners and editors get the document row's management actions; a
 * reader gets download and relations.
 */
export function useReaderActions({ slug, role, previewVersion, reload, downloadHref, relationsHref }: Params): ReaderActions {
  const queryClient = useQueryClient();
  const [renaming, setRenaming] = useState(false);
  // Editor+, the same boundary as the `/summary` endpoint.
  const allowed = role !== undefined && role !== "viewer";

  const asset =
    useQuery({ queryKey: qk.assetSummary(slug), queryFn: () => api.getAssetSummary(slug), enabled: allowed }).data ?? null;
  const projects =
    useQuery({
      ...projectListQuery,
      enabled: Boolean(asset?.project_id),
    }).data ?? NO_PROJECTS;

  const onChanged = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: qk.assetSummary(slug) });
    // The lists show the same asset; without this they keep the old title or project.
    await queryClient.invalidateQueries({ queryKey: qk.assets() });
    await reload();
  }, [queryClient, slug, reload]);

  const { actions, onCommitRename, onPinChanged, dialogs } = useAssetActions(onChanged, {
    onDeleted: () => navigate("/"),
  });

  const project = asset?.project_id ? (projects.find((p) => p.id === asset.project_id) ?? null) : null;
  const reading: MenuAction[] = [
    ...(downloadHref
      ? [{ key: "download", label: t("reader.download"), icon: Download, onClick: () => window.location.assign(downloadHref) }]
      : []),
    ...(relationsHref
      ? [{ key: "relations", label: t("relations.title"), icon: Network, onClick: () => navigate(relationsHref) }]
      : []),
  ];

  if (!asset) return { asset: null, project: null, menu: reading, share: null, dialogs: null, onChanged, assignProject: null };

  const pinned = Boolean(asset.pinned_at);
  const managed = buildAssetMenuActions(asset, actions, {
    onRename: () => setRenaming(true),
    allowContentEdits: previewVersion === null,
    previewVersion,
  });
  const shareAction = managed.find((a) => a.key === "share");
  const menu: MenuAction[] = [
    { key: "pin", label: t(pinned ? "pinButton.remove" : "pinButton.add"), icon: Star, onClick: () => void togglePin(asset.id, pinned, onPinChanged) },
    ...reading,
    // Sharing has its own toolbar button; a blocked one stays in the menu with its reason.
    ...managed.filter((a) => a.key !== "share" || a.disabled).map((a, i) => (i === 0 ? { ...a, heading: t("reader.manage") } : a)),
  ];

  return {
    asset,
    project,
    menu,
    share: canManage(asset) && shareAction && !shareAction.disabled ? () => actions.onShare(asset) : null,
    dialogs: (
      <>
        {dialogs}
        {renaming && (
          <RenameDialog
            title={asset.title ?? asset.slug}
            onClose={() => setRenaming(false)}
            onRename={async (next) => {
              await onCommitRename(asset.id, next);
              setRenaming(false);
            }}
          />
        )}
      </>
    ),
    onChanged,
    assignProject: managed.some((a) => a.key === "project") ? () => actions.onProject(asset) : null,
  };
}
