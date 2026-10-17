import {
  Bot,
  FolderInput,
  GitCompare,
  GitMerge,
  History,
  Pencil,
  Share2,
  Trash2,
  Upload,
} from "lucide-react";

import type { AssetSummary } from "../api";
import type { MenuAction } from "../components/ui/menuAction";
import { agentViewHref } from "./agentView";
import { canEdit, canManage } from "./assetRoles";
import { t } from "./i18n";
import { navigate } from "./navigate";
import type { AssetRowActions } from "./useAssetActions";

interface Options {
  /** Enters the surface's own rename affordance (inline input on a row,
   * title field in the viewer toolbar). */
  onRename: () => void;
  /**
   * Whether content may be changed. `false` when previewing an archived
   * version: a write would hit the current version, so updating while on v1
   * would silently overwrite v5. Promoting old content is what restore is for.
   */
  allowContentEdits?: boolean;
  /** Archived version in view; the agent view opens the same version. */
  previewVersion?: number | null;
}

/**
 * The management actions an asset carries, in one order, gated by
 * `my_role`. Single source of truth for the list row (desktop icon
 * cluster + mobile sheet) and the viewer's toolbar, so a file offers the
 * same operations wherever the user meets it.
 */
export function buildAssetMenuActions(
  a: AssetSummary,
  actions: AssetRowActions,
  { onRename, allowContentEdits = true, previewVersion = null }: Options,
): MenuAction[] {
  const canMgr = canManage(a);
  const canEd = canEdit(a);
  const shareBlocked = a.security_status === "critical" && !a.security_bypass;
  const out: MenuAction[] = [];

  if (canEd)
    out.push({ key: "rename", label: t("assetMenu.rename"), icon: Pencil, onClick: onRename });
  if (canEd && allowContentEdits)
    out.push({
      key: "update",
      label: t("assetMenu.update"),
      icon: Upload,
      onClick: () => actions.onUpdate(a),
    });
  // History, read-only preview and comparison are for everyone with access to
  // the asset, not just editors. The restore mutation is gated inside the
  // dialog.
  if (a.version > 1)
    out.push({
      key: "versions",
      label: t("assetMenu.versions", { count: a.version }),
      icon: History,
      onClick: () => actions.onVersions(a),
    });
  if (a.version > 1)
    out.push({
      key: "diff",
      label: t("assetMenu.diff"),
      icon: GitCompare,
      onClick: () => navigate(`/v/${a.slug}/diff`),
    });
  // What an MCP agent reads from the asset: a tool for whoever maintains
  // the content, so editor+ like the endpoint behind it.
  if (canEd)
    out.push({
      key: "agentView",
      label: t("assetMenu.agentView"),
      icon: Bot,
      onClick: () => navigate(agentViewHref(a.slug, { version: previewVersion ?? undefined })),
    });
  // Moving a file between projects is owner-only on the backend (file owner
  // or project owner); an editor would get a 404.
  if (canMgr)
    out.push({
      key: "project",
      label: t("assetMenu.project"),
      icon: FolderInput,
      onClick: () => actions.onProject(a),
    });
  if (canMgr)
    out.push({
      key: "binding",
      label: t("assetMenu.binding"),
      icon: GitMerge,
      onClick: () => actions.onBinding(a),
    });
  if (canMgr)
    out.push({
      key: "share",
      label: t("common.share"),
      icon: Share2,
      onClick: () => actions.onShare(a),
      disabled: shareBlocked,
      disabledHint: t("assetMenu.shareBlocked"),
    });
  if (canMgr)
    out.push({ key: "delete", label: t("common.delete"), icon: Trash2, danger: true, onClick: () => actions.onDelete(a) });

  return out;
}
