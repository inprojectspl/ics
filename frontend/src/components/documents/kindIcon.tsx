import { clsx } from "clsx";
import { BookOpenText, FileCode2, FileText, FileType2, FolderTree, type LucideIcon, type LucideProps } from "lucide-react";
import type { AssetKind } from "../../api";
import type { MessageKey } from "../../lib/i18n";

/**
 * One glyph and one name per document kind, used by every list, the
 * command palette and the reader. The kind is told by the icon and the
 * word, never by tinting a whole row.
 */
const KIND_ICON: Record<AssetKind, LucideIcon> = {
  md_single: FileText,
  md_collection: FolderTree,
  html_bundle: FileCode2,
  pdf_doc: BookOpenText,
  office_doc: FileType2,
};

export const KIND_LABEL: Record<AssetKind, MessageKey> = {
  md_single: "kind.mdSingle",
  md_collection: "kind.mdCollection",
  html_bundle: "kind.htmlBundle",
  pdf_doc: "kind.pdfDoc",
  office_doc: "kind.officeDoc",
};

export function kindIcon(kind: AssetKind): LucideIcon {
  return KIND_ICON[kind];
}

/** The kind's glyph as an element. */
export function KindIcon({ kind, ...props }: LucideProps & { kind: AssetKind }) {
  const Icon = KIND_ICON[kind];
  return <Icon {...props} />;
}

/** The kind's glyph on its square tile, the leading column of document rows. */
export function KindTile({ kind, className }: { kind: AssetKind; className?: string }) {
  return (
    <span
      aria-hidden
      className={clsx(
        "grid size-9 shrink-0 place-items-center rounded-control bg-surface-subtle text-text-secondary ring-1 ring-inset ring-border",
        className,
      )}
    >
      <KindIcon kind={kind} size={18} strokeWidth={1.75} />
    </span>
  );
}
