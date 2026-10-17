import { ReactNode, useCallback, useMemo, useState } from "react";

import { api, AssetSummary } from "../api";
import { BindingDialog } from "../components/BindingDialog";
import { useConfirm } from "../components/ConfirmDialog";
import { MoveToProjectDialog } from "../components/MoveToProjectDialog";
import { ShareDialog } from "../components/ShareDialog";
import { useToast } from "../components/Toast";
import { UpdateAssetDialog } from "../components/UpdateAssetDialog";
import { VersionsDialog } from "../components/VersionsDialog";
import { formatApiError } from "./apiError";
import { t } from "./i18n";

export interface AssetRowActions {
  onUpdate: (asset: AssetSummary) => void;
  onVersions: (asset: AssetSummary) => void;
  onProject: (asset: AssetSummary) => void;
  onBinding: (asset: AssetSummary) => void;
  onShare: (asset: AssetSummary) => void;
  onDelete: (asset: AssetSummary) => void;
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

  const onDelete = useCallback(
    async (a: AssetSummary) => {
      const title = a.title ?? a.slug;
      const ok = await confirm({
        title: t("assetActions.deleteTitle", { title }),
        message: t("assetActions.deleteMessage"),
        confirmLabel: t("common.delete"),
        destructive: true,
      });
      if (!ok) return;
      try {
        await api.deleteAsset(a.id);
        toast(t("assetActions.deleted", { title }), "success");
        // A reader of a deleted asset has nothing to refresh; the caller
        // navigates away instead of triggering a 404 on reload.
        if (onDeleted) onDeleted();
        else await onChanged();
      } catch (e) {
        toast(formatApiError(e, t("assetActions.deleteFailed")), "error");
      }
    },
    [confirm, toast, onChanged, onDeleted],
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
    }),
    [onDelete],
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
