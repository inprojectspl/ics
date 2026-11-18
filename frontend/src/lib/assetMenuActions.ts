import {
  Archive,
  ArchiveRestore,
  Bot,
  FolderInput,
  GitCompare,
  GitMerge,
  History,
  Pencil,
  RotateCcw,
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
   * Whether content may be changed. `false` when previewing an earlier
   * version: a write would hit the current version, so updating while on v1
   * would silently overwrite v5. Promoting old content is what restore is for.
   */
  allowContentEdits?: boolean;
  /** Earlier version in view; the agent view opens the same version. */
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
  // A micro-application's package is published and versioned through
  // ICS-MCP only; the API refuses content, version and binding operations
  // on it (`microapp_requires_agent_api`, `microapp_source_restricted`).
  const content = a.kind !== "micro_application";
  const out: MenuAction[] = [];

  // In the trash only the way back and the way out remain.
  if (a.deleted_at)
    return [
      { key: "restore", label: t("assetActions.restore"), icon: RotateCcw, onClick: () => actions.onRestore(a) },
      { key: "purge", label: t("assetActions.purge"), icon: Trash2, danger: true, onClick: () => actions.onPurge(a) },
    ];

  if (canEd)
    out.push({ key: "rename", label: t("assetMenu.rename"), icon: Pencil, onClick: onRename });
  if (canEd && allowContentEdits && content)
    out.push({
      key: "update",
      label: t("assetMenu.update"),
      icon: Upload,
      onClick: () => actions.onUpdate(a),
    });
  // History, read-only preview and comparison are for everyone with access to
  // the asset, not just editors. The restore mutation is gated inside the
  // dialog. A micro-application's history is its package's, so it is for its
  // publishers: the viewer knows (`history_readable`), a list row knows the owners.
  const history = a.version > 1 && (a.history_readable ?? (content || canMgr));
  if (history)
    out.push({
      key: "versions",
      label: t("assetMenu.versions", { count: a.version }),
      icon: History,
      onClick: () => actions.onVersions(a),
    });
  if (history)
    out.push({
      key: "diff",
      label: t("assetMenu.diff"),
      icon: GitCompare,
      onClick: () => navigate(`/v/${a.slug}/diff`),
    });
  // What an MCP agent reads from the asset: a tool for whoever maintains
  // the content, so editor+ like the endpoint behind it.
  if (canEd && content)
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
  if (canMgr && content)
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
  // Archive and trash are structural, like moving and sharing: owners only.
  if (canMgr)
    out.push(
      {
        key: "archive",
        label: t(a.archived_at ? "assetMenu.unarchive" : "assetMenu.archive"),
        icon: a.archived_at ? ArchiveRestore : Archive,
        onClick: () => actions.onArchive(a),
      },
      {
        key: "delete",
        label: t("assetActions.moveToTrash"),
        icon: Trash2,
        danger: true,
        onClick: () => actions.onDelete(a),
      },
    );

  return out;
}
