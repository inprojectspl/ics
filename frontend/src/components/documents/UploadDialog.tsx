import { useRef, useState, type DragEvent } from "react";
import { clsx } from "clsx";
import { Building2, FolderUp, Globe2, Loader2, UploadCloud } from "lucide-react";
import type { UploadShareMode } from "../../api";
import { t } from "../../lib/i18n";
import { buttonClass } from "../ui/Button";
import { Dialog } from "../ui/Dialog";

const ACCEPT =
  ".md,.pdf,.docx,.odt,.doc,.html,.htm,.css,.js,.mjs,.json,.svg,.png,.jpg,.jpeg,.webp,.gif,.ico,.avif,.woff,.woff2,.txt";

interface Props {
  mode: UploadShareMode;
  onModeChange: (m: UploadShareMode) => void;
  uploading: boolean;
  onPicked: (list: FileList | null) => Promise<void>;
  onDrop: (dt: DataTransfer) => Promise<void>;
  onClose: () => void;
  /** Name of the project the files go to, when uploading from a project. */
  projectName?: string;
}

const MODES: ReadonlyArray<{
  value: UploadShareMode;
  icon: typeof Globe2;
  title: "upload.modeOrg" | "upload.modePublic";
  body: "upload.modeOrgBody" | "upload.modePublicBody";
}> = [
  { value: "org_sso", icon: Building2, title: "upload.modeOrg", body: "upload.modeOrgBody" },
  { value: "public", icon: Globe2, title: "upload.modePublic", body: "upload.modePublicBody" },
];

/**
 * Uploading in one step: who will see the new documents, then the files.
 * The drop area accepts files and folders; the file inputs stay available
 * for keyboards and phones without drag and drop.
 */
export function UploadDialog({ mode, onModeChange, uploading, onPicked, onDrop, onClose, projectName }: Props) {
  const [over, setOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const dirRef = useRef<HTMLInputElement>(null);

  const finish = async (run: Promise<void>) => {
    await run;
    onClose();
  };
  const onDropFiles = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    if (e.dataTransfer.items?.length || e.dataTransfer.files.length) void finish(onDrop(e.dataTransfer));
  };

  return (
    <Dialog title={t("upload.title")} eyebrow={projectName ? t("upload.toProject", { name: projectName }) : undefined} onClose={onClose} maxWidth="lg">
      <div className="space-y-5 px-5 py-5 sm:px-6">
        <fieldset>
          <legend className="mb-2 text-ui font-medium text-text-primary">{t("upload.whoSees")}</legend>
          <div className="grid gap-2 sm:grid-cols-2">
            {MODES.map((m) => {
              const on = mode === m.value;
              return (
                <label
                  key={m.value}
                  className={clsx(
                    "flex cursor-pointer gap-3 rounded-card border p-3 transition-colors duration-150",
                    on ? "border-accent bg-accent-soft" : "border-border hover:bg-surface-hover",
                  )}
                >
                  <input
                    type="radio"
                    name="upload-mode"
                    value={m.value}
                    checked={on}
                    onChange={() => onModeChange(m.value)}
                    className="mt-0.5 size-4 shrink-0 accent-accent"
                  />
                  <span className="min-w-0">
                    <span className="flex items-center gap-1.5 text-ui font-medium text-text-primary">
                      <m.icon size={15} aria-hidden className={on ? "text-accent" : "text-text-secondary"} />
                      {t(m.title)}
                    </span>
                    <span className="mt-0.5 block text-meta text-text-secondary">{t(m.body)}</span>
                  </span>
                </label>
              );
            })}
          </div>
        </fieldset>

        <div
          onDragOver={(e) => {
            e.preventDefault();
            setOver(true);
          }}
          onDragLeave={() => setOver(false)}
          onDrop={onDropFiles}
          className={clsx(
            "rounded-card border-2 border-dashed px-5 py-8 text-center transition-colors duration-150",
            over ? "border-accent bg-accent-soft" : "border-border-strong bg-surface-subtle",
          )}
        >
          {uploading ? (
            <p role="status" className="flex items-center justify-center gap-2 text-body text-text-primary">
              <Loader2 size={18} aria-hidden className="animate-spin text-accent" />
              {t("uploadCard.uploading")}
            </p>
          ) : (
            <>
              <UploadCloud size={28} strokeWidth={1.5} aria-hidden className={clsx("mx-auto mb-2", over ? "text-accent" : "text-text-secondary")} />
              <p className="text-body text-text-primary">{t(over ? "uploadCard.dropHere" : "upload.dropPrompt")}</p>
              <div className="mt-3 flex flex-wrap items-center justify-center gap-2">
                <button
                  type="button"
                  onClick={() => fileRef.current?.click()}
                  className={buttonClass("primary")}
                >
                  <UploadCloud size={16} aria-hidden />
                  {t("upload.pickFiles")}
                </button>
                <button
                  type="button"
                  onClick={() => dirRef.current?.click()}
                  className={buttonClass("secondary")}
                >
                  <FolderUp size={16} aria-hidden />
                  {t("upload.pickFolder")}
                </button>
              </div>
            </>
          )}
        </div>

        <ul className="space-y-1 text-meta text-text-secondary">
          <li>{t("upload.hintFiles")}</li>
          <li>{t("upload.hintFolder")}</li>
        </ul>

        <input
          ref={fileRef}
          type="file"
          multiple
          accept={ACCEPT}
          className="sr-only"
          tabIndex={-1}
          aria-label={t("upload.pickFiles")}
          onChange={(e) => {
            const input = e.currentTarget;
            void finish(onPicked(input.files).finally(() => (input.value = "")));
          }}
        />
        <input
          ref={dirRef}
          type="file"
          className="sr-only"
          tabIndex={-1}
          aria-label={t("upload.pickFolder")}
          {...({ webkitdirectory: "", directory: "" } as Record<string, string>)}
          onChange={(e) => {
            const input = e.currentTarget;
            void finish(onPicked(input.files).finally(() => (input.value = "")));
          }}
        />
      </div>
    </Dialog>
  );
}
