import { Download, FilePlus2, Upload } from "lucide-react";
import { t } from "../../lib/i18n";
import { FileTree } from "../FileTree";
import { PanelAction, PanelLink, PanelSection } from "../ui/PanelSection";

interface Props {
  tree: string[];
  currentPath: string;
  onSelect: (path: string) => void;
  onCreateFile?: () => void;
  onUploadFile?: () => void;
  onDeleteFile?: (path: string) => void;
  onMoveFile?: (fromPath: string, toFolder: string) => void;
  downloadHref?: string;
}

/** The files of a collection in the reader inspector: the tree, and for
 * editors adding a file; the ZIP for everyone. */
export function CollectionFiles({
  tree,
  currentPath,
  onSelect,
  onCreateFile,
  onUploadFile,
  onDeleteFile,
  onMoveFile,
  downloadHref,
}: Props) {
  return (
    <div>
      <PanelSection title={t("collectionLayout.files")} aside={<span className="text-meta tabular-nums text-text-secondary">{tree.length}</span>}>
        <FileTree paths={tree} current={currentPath} onSelect={onSelect} onDelete={onDeleteFile} onMove={onMoveFile} />
      </PanelSection>
      {(onCreateFile || onUploadFile || downloadHref) && (
        <PanelSection title={t("collectionLayout.actions")} last>
          <div className="-mx-2 flex flex-col gap-0.5">
            {onCreateFile && (
              <PanelAction icon={<FilePlus2 size={15} aria-hidden />} label={t("collectionLayout.newFile")} title={t("collectionLayout.newFileTitle")} onClick={onCreateFile} />
            )}
            {onUploadFile && (
              <PanelAction icon={<Upload size={15} aria-hidden />} label={t("collectionLayout.upload")} title={t("collectionLayout.uploadTitle")} onClick={onUploadFile} />
            )}
            {downloadHref && (
              <PanelLink href={downloadHref} icon={<Download size={15} aria-hidden />} label={t("collectionLayout.zip")} title={t("collectionLayout.zipTitle")} download />
            )}
          </div>
        </PanelSection>
      )}
    </div>
  );
}
