import { useRef, useState } from "react";
import { clsx } from "clsx";
import { FolderUp, UploadCloud } from "lucide-react";
import { api, AssetKind, AssetSummary } from "../api";
import { formatApiError } from "../lib/apiError";
import { t, type MessageKey } from "../lib/i18n";
import { isOfficeFileName, walkDataTransfer, WalkedFile } from "../lib/directoryWalker";
import { ChangeNoteField, changeNoteParam } from "./ChangeNoteField";
import { KIND_LABEL } from "./documents/kindIcon";
import { buttonClass } from "./ui/Button";
import { Dialog } from "./ui/Dialog";

interface Props {
  asset: AssetSummary;
  onClose: () => void;
  onUpdated: () => void;
}

const KIND_HINT: Record<AssetKind, MessageKey> = {
  md_single: "updateAsset.hintMdSingle",
  md_collection: "updateAsset.hintMdCollection",
  html_bundle: "updateAsset.hintHtmlBundle",
  pdf_doc: "updateAsset.hintPdfDoc",
  office_doc: "updateAsset.hintOfficeDoc",
};

const hasExtension = (ext: string) => (name: string) => name.toLowerCase().endsWith(ext);

/** Kinds whose version is exactly one file of the given type. */
const SINGLE_FILE: Partial<
  Record<AssetKind, { accepts: (name: string) => boolean; error: MessageKey; picker: string }>
> = {
  md_single: { accepts: hasExtension(".md"), error: "updateAsset.needOneMd", picker: ".md" },
  pdf_doc: { accepts: hasExtension(".pdf"), error: "updateAsset.needOnePdf", picker: ".pdf" },
  // The new version may switch format (e.g. .doc to .docx).
  office_doc: { accepts: isOfficeFileName, error: "updateAsset.needOneOffice", picker: ".docx,.odt,.doc" },
};

/** File picker filter for the multi-file kinds; the folder picker takes everything. */
const MULTI_ACCEPT: Partial<Record<AssetKind, string>> = {
  md_collection: ".md",
  html_bundle:
    ".html,.htm,.css,.js,.mjs,.json,.svg,.png,.jpg,.jpeg,.webp,.gif,.ico,.avif,.woff,.woff2,.txt",
};

export function UpdateAssetDialog({ asset, onClose, onUpdated }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [changeNote, setChangeNote] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const dirRef = useRef<HTMLInputElement>(null);
  const single = SINGLE_FILE[asset.kind];

  const upload = async (walked: WalkedFile[]) => {
    setError(null);
    setBusy(true);
    try {
      let payload = walked;
      if (single) {
        const matching = walked.filter((w) => single.accepts(w.path));
        if (matching.length !== 1) {
          setError(t(single.error));
          return;
        }
        payload = matching;
      } else if (asset.kind === "md_collection") {
        payload = walked.filter((w) => w.path.toLowerCase().endsWith(".md"));
        if (payload.length === 0) {
          setError(t("updateAsset.noMd"));
          return;
        }
      }
      await api.uploadVersion(asset.id, payload, changeNoteParam(changeNote));
      onUpdated();
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  };

  const onDrop = async (dt: DataTransfer) => {
    const walked = await walkDataTransfer(dt.items);
    if (walked.length === 0 && dt.files.length > 0) {
      const fromList = Array.from(dt.files).map((f) => ({ file: f, path: f.name }));
      await upload(fromList);
    } else {
      await upload(walked);
    }
  };

  // Same path convention as a dropped folder: relative to the picked root, root included.
  const onPicked = async (input: HTMLInputElement) => {
    const list = Array.from(input.files ?? []);
    input.value = "";
    if (list.length === 0 || busy) return;
    await upload(
      list.map((f) => ({ file: f, path: (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name })),
    );
  };

  return (
    <Dialog eyebrow={t("updateAsset.eyebrow")} title={asset.title || asset.slug} onClose={onClose} maxWidth="lg">
        <section className="px-6 py-6">
          <p className="text-ui text-text-secondary mb-4">
            {t(KIND_HINT[asset.kind])} {t("updateAsset.archiveNote")}
          </p>
          <ChangeNoteField
            value={changeNote}
            onChange={setChangeNote}
            disabled={busy}
            className="mb-4"
          />
          <div
            className={clsx(
              "rounded-control border-2 border-dashed py-8 px-4 text-center transition-colors",
              dragActive ? "border-accent bg-accent-soft/40" : "border-border bg-surface",
            )}
            onDragOver={(e) => {
              e.preventDefault();
              setDragActive(true);
            }}
            onDragLeave={() => setDragActive(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragActive(false);
              if (busy) return;
              if (e.dataTransfer.items.length || e.dataTransfer.files.length) {
                void onDrop(e.dataTransfer);
              }
            }}
          >
            <p className="text-body text-text-primary mb-1">
              {busy ? t("uploadCard.uploading") : t("updateAsset.dropHere")}
            </p>
            <p className="text-meta text-text-tertiary">
              {t("updateAsset.kind", { kind: t(KIND_LABEL[asset.kind]) })} ·{" "}
              {t("updateAsset.nextVersion", { version: asset.version + 1 })}
            </p>
            <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
              <button
                type="button"
                disabled={busy}
                onClick={() => fileRef.current?.click()}
                className={buttonClass("primary")}
              >
                <UploadCloud size={16} aria-hidden />
                {t(single ? "updateAsset.pickFile" : "upload.pickFiles")}
              </button>
              {!single && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => dirRef.current?.click()}
                  className={buttonClass("secondary")}
                >
                  <FolderUp size={16} aria-hidden />
                  {t("upload.pickFolder")}
                </button>
              )}
            </div>
          </div>
          <input
            ref={fileRef}
            type="file"
            multiple={!single}
            accept={single?.picker ?? MULTI_ACCEPT[asset.kind]}
            className="sr-only"
            tabIndex={-1}
            aria-label={t(single ? "updateAsset.pickFile" : "upload.pickFiles")}
            onChange={(e) => void onPicked(e.currentTarget)}
          />
          {!single && (
            <input
              ref={dirRef}
              type="file"
              className="sr-only"
              tabIndex={-1}
              aria-label={t("upload.pickFolder")}
              {...({ webkitdirectory: "", directory: "" } as Record<string, string>)}
              onChange={(e) => void onPicked(e.currentTarget)}
            />
          )}
          {error && <p className="mt-4 text-ui text-danger">{error}</p>}
        </section>
    </Dialog>
  );
}
