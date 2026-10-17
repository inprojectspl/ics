/**
 * Vault file mutations from the viewer sidebar: .md upload, empty file,
 * move, delete. A hook because every handler needs `useToast`, `useConfirm`
 * and `reload` from `useCollectionDoc`.
 */

import { useCallback, useRef, useState } from "react";
import { api } from "../api";
import { useConfirm } from "../components/ConfirmDialog";
import { useToast } from "../components/Toast";
import { formatApiError } from "./apiError";
import { t } from "./i18n";
import type { ReloadOpts } from "./useCollectionDoc";

interface Opts {
  assetId: string;
  activePath: string;
  reload: (opts?: ReloadOpts) => Promise<void>;
  /** Called after an empty file is created, so the view enters the editor
   * only once reload has set the new `activePath`. */
  onEnterEditor: () => void;
}

export function useVaultFileActions({ assetId, activePath, reload, onEnterEditor }: Opts) {
  const { toast } = useToast();
  const confirm = useConfirm();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [newFileOpen, setNewFileOpen] = useState(false);

  const openFilePicker = useCallback(() => fileInputRef.current?.click(), []);

  const onPickedFile = useCallback(
    async (list: FileList | null) => {
      if (!list || list.length === 0) return;
      const file = list[0];
      if (!file || !file.name.toLowerCase().endsWith(".md")) {
        toast(t("vaultFileActions.mdOnly"), "error");
        return;
      }
      try {
        const res = await api.addVaultFile(assetId, file);
        toast(t("vaultFileActions.added", { path: res.added_path }), "success");
        await reload();
      } catch (e) {
        toast(formatApiError(e, t("vaultFileActions.addFailed")), "error");
      }
    },
    [assetId, reload, toast],
  );

  const onCreateEmptyFile = useCallback(
    async (relPath: string) => {
      const res = await api.createEmptyVaultFile(assetId, relPath);
      toast(t("vaultFileActions.created", { path: res.added_path }), "success");
      setNewFileOpen(false);
      // Wait for the tree refresh + navigation to settle before entering
      // editing mode - InlineEditor reads `editPath = activePath`, so
      // flipping `editing` before reload would open the previous file.
      await reload({ activeAfter: res.added_path });
      onEnterEditor();
    },
    [assetId, onEnterEditor, reload, toast],
  );

  const onMoveFile = useCallback(
    async (fromPath: string, toFolder: string) => {
      const baseName = fromPath.split("/").pop() || fromPath;
      const toPath = toFolder ? `${toFolder}/${baseName}` : baseName;
      try {
        const res = await api.moveVaultFile(assetId, fromPath, toPath);
        toast(t("vaultFileActions.moved", { name: baseName, folder: toFolder || "/" }), "success");
        await reload({
          activeAfter: fromPath === activePath ? res.to_path : activePath,
        });
      } catch (e) {
        toast(formatApiError(e, t("vaultFileActions.moveFailed")), "error");
      }
    },
    [activePath, assetId, reload, toast],
  );

  const onDeleteFile = useCallback(
    async (p: string) => {
      const ok = await confirm({
        title: t("vaultFileActions.deleteTitle", { path: p }),
        message: t("vaultFileActions.deleteMessage"),
        confirmLabel: t("common.delete"),
        destructive: true,
      });
      if (!ok) return;
      try {
        const res = await api.deleteVaultFile(assetId, p);
        toast(t("vaultFileActions.deleted", { path: p }), "success");
        // If we just deleted the currently-viewed file, jump to the new
        // entry the backend picked for us (readme/index/alphabetical).
        await reload({
          activeAfter: p === activePath ? res.entry_path : activePath,
        });
      } catch (e) {
        toast(formatApiError(e, t("vaultFileActions.deleteFailed")), "error");
      }
    },
    [activePath, assetId, confirm, reload, toast],
  );

  return {
    fileInputRef,
    newFileOpen,
    setNewFileOpen,
    openFilePicker,
    onPickedFile,
    onCreateEmptyFile,
    onMoveFile,
    onDeleteFile,
  };
}
