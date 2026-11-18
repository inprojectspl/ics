import { ReactNode, useCallback, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api, AssetSummary } from "../api";
import { BindingDialog } from "../components/BindingDialog";
import { useConfirm } from "../components/ConfirmDialog";
import { MoveToProjectDialog } from "../components/MoveToProjectDialog";
import { ShareDialog } from "../components/ShareDialog";
import { useToast } from "../components/Toast";
import { UpdateAssetDialog } from "../components/UpdateAssetDialog";
import { VersionsDialog } from "../components/VersionsDialog";
import { formatApiError } from "./apiError";
import { t, tn } from "./i18n";
import { navigate } from "./navigate";
import { authConfigQuery } from "./queries";

// What the server keeps deleted documents for unless configured otherwise.
const DEFAULT_TRASH_DAYS = 30;

/** Days a deleted document waits in the trash (server setting). */
function useTrashRetentionDays(): number {
  const { data } = useQuery(authConfigQuery);
  return data?.trash_retention_days ?? DEFAULT_TRASH_DAYS;
}

export interface AssetRowActions {
  onUpdate: (asset: AssetSummary) => void;
  onVersions: (asset: AssetSummary) => void;
  onProject: (asset: AssetSummary) => void;
  onBinding: (asset: AssetSummary) => void;
  onShare: (asset: AssetSummary) => void;
  onDelete: (asset: AssetSummary) => void;
  /** Into the archive, or back out of it when it is there. */
  onArchive: (asset: AssetSummary) => void;
  /** Out of the trash. */
  onRestore: (asset: AssetSummary) => void;
  /** From the trash, for good. */
  onPurge: (asset: AssetSummary) => void;
}

/** Plain pin toggle for surfaces without their own busy state (mobile
 * action sheet, viewer toolbar). `PinButton` owns the desktop star. */
export async function togglePin(
  assetId: string,
  pinned: boolean,
  onToggled: (p: boolean) => void,
) {
  try {
    if (pinned) {
      await api.unpinAsset(assetId);
      onToggled(false);
    } else {
      await api.pinAsset(assetId);
      onToggled(true);
    }
  } catch {
    // Not reported: onToggled is skipped, so the star keeps its old state.
  }
}

export interface AssetActions {
  /** Callback bundle for `AssetRow` / the viewer toolbar. Stable identity. */
  actions: AssetRowActions;
  onCommitRename: (assetId: string, next: string) => Promise<void>;
  onPinChanged: (pinned: boolean) => Promise<void>;
  /** Every dialog the actions can open. Render once per consumer. */
  dialogs: ReactNode;
}

/**
 * Asset management actions and their dialog state, shared by the home list,
 * the project file list and the viewer toolbar. `onChanged` lets the caller
 * refetch; the caller also decides from `my_role` which actions to show.
 */
export function useAssetActions(
  onChanged: () => void | Promise<void>,
  { onDeleted }: { onDeleted?: () => void } = {},
): AssetActions {
  const [shareFor, setShareFor] = useState<AssetSummary | null>(null);
  const [updateFor, setUpdateFor] = useState<AssetSummary | null>(null);
  const [versionsFor, setVersionsFor] = useState<AssetSummary | null>(null);
  const [projectFor, setProjectFor] = useState<AssetSummary | null>(null);
  const [bindingFor, setBindingFor] = useState<AssetSummary | null>(null);

  const { toast } = useToast();
  const confirm = useConfirm();
  const trashDays = useTrashRetentionDays();

  // Shared by the row button and the undo of a delete. A reader that just
  // left a deleted asset goes back to it.
  const restore = useCallback(
    async (a: AssetSummary) => {
      const title = a.title ?? a.slug;
      try {
        await api.restoreAsset(a.id);
        toast(t("assetActions.restored", { title }), "success");
        if (onDeleted) navigate(`/v/${a.slug}`);
        else await onChanged();
      } catch (e) {
        toast(formatApiError(e, t("assetActions.restoreFailed")), "error");
      }
    },
    [toast, onChanged, onDeleted],
  );

  const onDelete = useCallback(
    async (a: AssetSummary) => {
      const title = a.title ?? a.slug;
      const ok = await confirm({
        title: t("assetActions.deleteTitle", { title }),
        // An app also stops for everyone and its roles go; its data stays
        // with the asset in the trash.
        message: [
          tn("assetActions.trashNote", trashDays),
          t(a.kind === "micro_application" ? "assetActions.deleteAppMessage" : "assetActions.deleteMessage"),
        ].join(" "),
        confirmLabel: t("assetActions.moveToTrash"),
        destructive: true,
      });
      if (!ok) return;
      try {
        await api.deleteAsset(a.id);
        toast(t("assetActions.deleted", { title }), "success", {
          label: t("common.undo"),
          onClick: () => void restore(a),
        });
        // A reader of a deleted asset has nothing to refresh; the caller
        // navigates away instead of triggering a 404 on reload.
        if (onDeleted) onDeleted();
        else await onChanged();
      } catch (e) {
        toast(formatApiError(e, t("assetActions.deleteFailed")), "error");
      }
    },
    [confirm, toast, onChanged, onDeleted, restore, trashDays],
  );

  const onArchive = useCallback(
    async (a: AssetSummary) => {
      const title = a.title ?? a.slug;
      const archiving = !a.archived_at;
      const flip = (into: boolean) => (into ? api.archiveAsset(a.id) : api.unarchiveAsset(a.id));
      try {
        await flip(archiving);
        toast(t(archiving ? "assetActions.archived" : "assetActions.unarchived", { title }), "success", {
          label: t("common.undo"),
          onClick: () =>
            void flip(!archiving).then(onChanged, (e) => toast(formatApiError(e, t("assetActions.archiveFailed")), "error")),
        });
        await onChanged();
      } catch (e) {
        toast(formatApiError(e, t("assetActions.archiveFailed")), "error");
      }
    },
    [toast, onChanged],
  );

  const onPurge = useCallback(
    async (a: AssetSummary) => {
      const title = a.title ?? a.slug;
      const ok = await confirm({
        title: t("assetActions.purgeTitle", { title }),
        message: t("assetActions.purgeMessage"),
        confirmLabel: t("assetActions.purge"),
        destructive: true,
      });
      if (!ok) return;
      try {
        await api.purgeAsset(a.id);
        toast(t("assetActions.purged", { title }), "success");
        await onChanged();
      } catch (e) {
        toast(formatApiError(e, t("assetActions.purgeFailed")), "error");
      }
    },
    [confirm, toast, onChanged],
  );

  const onCommitRename = useCallback(
    async (assetId: string, next: string) => {
      try {
        await api.renameAsset(assetId, next);
        toast(t("assetActions.renamed"), "success");
        await onChanged();
      } catch (e) {
        toast(formatApiError(e, t("assetActions.renameFailed")), "error");
      }
    },
    [toast, onChanged],
  );

  const onPinChanged = useCallback(
    async (pinned: boolean) => {
      toast(t(pinned ? "assetActions.pinned" : "assetActions.unpinned"), "success");
      await onChanged();
    },
    [toast, onChanged],
  );

  // Stable callback bundle - `AssetRow` is memo()'d, so the reference must
  // survive parent rerenders. Setters are identity-stable; only onDelete
  // (a useCallback) is a real dependency.
  const actions = useMemo(
    () => ({
      onUpdate: setUpdateFor,
      onVersions: setVersionsFor,
      onProject: setProjectFor,
      onBinding: setBindingFor,
      onShare: setShareFor,
      onDelete,
      onArchive,
      onRestore: restore,
      onPurge,
    }),
    [onDelete, onArchive, restore, onPurge],
  );

  const dialogs = (
    <>
      {shareFor && <ShareDialog asset={shareFor} onClose={() => setShareFor(null)} />}
      {updateFor && (
        <UpdateAssetDialog
          asset={updateFor}
          onClose={() => setUpdateFor(null)}
          onUpdated={async () => {
            setUpdateFor(null);
            toast(t("assetActions.updated"), "success");
            await onChanged();
          }}
        />
      )}
      {versionsFor && (
        <VersionsDialog
          asset={versionsFor}
          onClose={() => setVersionsFor(null)}
          onRestored={onChanged}
        />
      )}
      {projectFor && (
        <MoveToProjectDialog
          asset={projectFor}
          onClose={() => setProjectFor(null)}
          onUpdated={async () => {
            setProjectFor(null);
            await onChanged();
          }}
        />
      )}
      {bindingFor && (
        <BindingDialog asset={bindingFor} onClose={() => setBindingFor(null)} />
      )}
    </>
  );

  return { actions, onCommitRename, onPinChanged, dialogs };
}

/**
 * "Empty trash" of the trash list: one's own trash or one project's, or with
 * `everyone` an administrator's whole-organisation trash, which the
 * confirmation names as such. The server purges in batches, so this repeats
 * until nothing is left.
 */
export function useEmptyTrash(onChanged: () => void | Promise<void>) {
  const { toast } = useToast();
  const confirm = useConfirm();
  return useCallback(
    async (count: number, { projectId, everyone = false }: { projectId?: string; everyone?: boolean } = {}) => {
      const ok = await confirm({
        title: t(
          everyone ? "trash.emptyEveryoneTitle" : projectId ? "trash.emptyProjectTitle" : "trash.emptyTitle",
        ),
        message: tn(everyone ? "trash.emptyEveryoneMessage" : "trash.emptyMessage", count),
        confirmLabel: t("trash.empty"),
        destructive: true,
      });
      if (!ok) return;
      let purged = 0;
      try {
        for (let round = 0; round < 20; round++) {
          const r = await api.emptyTrash(projectId, everyone);
          purged += r.purged;
          if (r.remaining === 0 || r.purged === 0) break;
        }
        toast(tn("trash.emptied", purged), "success");
      } catch (e) {
        toast(formatApiError(e, t("trash.emptyFailed")), "error");
      }
      await onChanged();
    },
    [confirm, toast, onChanged],
  );
}
