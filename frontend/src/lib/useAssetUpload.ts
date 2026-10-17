import { useCallback, useState } from "react";

import { api, UploadShareMode } from "../api";
import { useToast } from "../components/Toast";
import { formatApiError } from "./apiError";
import { t, tn } from "./i18n";
import {
  isCollectionDrop,
  isHtmlBundleDrop,
  isOfficeFileName,
  walkDataTransfer,
  WalkedFile,
} from "./directoryWalker";

interface UseAssetUploadOptions {
  uploadMode: UploadShareMode;
  /** When set, uploads are assigned to this project on creation. */
  projectId?: string;
  /** Called after a successful (or partially successful) ingest. */
  onUploaded: () => void | Promise<void>;
}

/**
 * Drop/pick to upload pipeline shared by the home dashboard and the project
 * page: classifies the drop (.md, .pdf, office document, collection, HTML
 * bundle) and calls the matching endpoint, into `projectId` when given.
 */
export function useAssetUpload({
  uploadMode,
  projectId,
  onUploaded,
}: UseAssetUploadOptions) {
  const [uploading, setUploading] = useState(false);
  const { toast } = useToast();

  const ingestWalked = useCallback(
    async (walked: WalkedFile[], fallback: File[]) => {
      const uploadSingles = async (files: File[]) => {
        let ok = 0;
        let skipped = 0;
        for (const f of files) {
          const name = f.name.toLowerCase();
          if (name.endsWith(".md")) {
            await api.uploadMarkdown(f, uploadMode, projectId);
          } else if (name.endsWith(".pdf")) {
            await api.uploadPdf(f, uploadMode, projectId);
          } else if (isOfficeFileName(name)) {
            await api.uploadDocument(f, uploadMode, projectId);
          } else {
            toast(t("assetUpload.skipped", { name: f.name }), "info");
            skipped++;
            continue;
          }
          ok++;
        }
        if (ok > 0) {
          toast(tn("assetUpload.uploaded", ok), "success");
        } else if (skipped === 0 && files.length > 0) {
          toast(t("assetUpload.nothing"), "info");
        }
      };

      setUploading(true);
      try {
        if (walked.length === 0) {
          await uploadSingles(fallback);
        } else if (isHtmlBundleDrop(walked)) {
          await api.uploadHtmlBundle(walked, uploadMode, projectId);
          toast(tn("assetUpload.bundleUploaded", walked.length), "success");
        } else if (isCollectionDrop(walked)) {
          const mdFiles = walked.filter((w) => w.path.toLowerCase().endsWith(".md"));
          if (mdFiles.length === 0) {
            toast(t("assetUpload.noMdFiles"), "error");
            return;
          }
          await api.uploadCollection(mdFiles, uploadMode, projectId);
          toast(tn("assetUpload.collectionUploaded", mdFiles.length), "success");
        } else {
          await uploadSingles(walked.map((w) => w.file));
        }
        await onUploaded();
      } catch (e) {
        toast(formatApiError(e, t("assetUpload.failed")), "error");
      } finally {
        setUploading(false);
      }
    },
    [uploadMode, projectId, onUploaded, toast],
  );

  const onDrop = useCallback(
    async (dt: DataTransfer) => {
      const walked = await walkDataTransfer(dt.items);
      await ingestWalked(walked, Array.from(dt.files));
    },
    [ingestWalked],
  );

  const onPicked = useCallback(
    async (list: FileList | null) => {
      if (!list || list.length === 0) return;
      const walked: WalkedFile[] = Array.from(list).map((f) => ({
        file: f,
        path: (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name,
      }));
      await ingestWalked(walked, Array.from(list));
    },
    [ingestWalked],
  );

  return { uploading, onDrop, onPicked };
}
