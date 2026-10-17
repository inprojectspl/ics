/**
 * Flattens a drag-and-dropped directory into files with POSIX paths relative
 * to the dropped root (e.g. "Vault/Notes/page.md"), via webkitGetAsEntry.
 */

export interface WalkedFile {
  file: File;
  path: string;
}

async function readEntries(reader: FileSystemDirectoryReader): Promise<FileSystemEntry[]> {
  // Spec: readEntries returns a batch at a time; loop until empty.
  const out: FileSystemEntry[] = [];
  for (;;) {
    const batch = await new Promise<FileSystemEntry[]>((resolve, reject) =>
      reader.readEntries(resolve, reject),
    );
    if (batch.length === 0) break;
    out.push(...batch);
  }
  return out;
}

async function walkEntry(entry: FileSystemEntry, prefix: string): Promise<WalkedFile[]> {
  if (entry.isFile) {
    const file = await new Promise<File>((resolve, reject) =>
      (entry as FileSystemFileEntry).file(resolve, reject),
    );
    return [{ file, path: prefix + entry.name }];
  }
  if (entry.isDirectory) {
    const reader = (entry as FileSystemDirectoryEntry).createReader();
    const children = await readEntries(reader);
    const nested = await Promise.all(children.map((c) => walkEntry(c, prefix + entry.name + "/")));
    return nested.flat();
  }
  return [];
}

export async function walkDataTransfer(items: DataTransferItemList): Promise<WalkedFile[]> {
  const entries: FileSystemEntry[] = [];
  for (const item of Array.from(items)) {
    const entry = item.webkitGetAsEntry?.();
    if (entry) entries.push(entry);
  }
  if (entries.length === 0) return [];
  const nested = await Promise.all(entries.map((e) => walkEntry(e, "")));
  return nested.flat();
}

export function isCollectionDrop(walked: WalkedFile[]): boolean {
  if (walked.length < 2) return false;
  // Treat any drop with >= 1 nested path or >= 2 .md files at root as a collection.
  const mdFiles = walked.filter((w) => w.path.toLowerCase().endsWith(".md"));
  return mdFiles.length >= 2 || walked.some((w) => w.path.includes("/"));
}

/** Word/ODF text documents stored as an office_doc; the backend detects
 * the real format from the content, the extension only routes the upload. */
const OFFICE_EXTENSIONS = [".docx", ".odt", ".doc"] as const;

export function isOfficeFileName(name: string): boolean {
  const lower = name.toLowerCase();
  return OFFICE_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

export function isHtmlBundleDrop(walked: WalkedFile[]): boolean {
  // Has at least one .html file. If both .md and .html are present, the
  // .html signal wins - typical "AI-generated demo with a README.md
  // alongside index.html" case.
  return walked.some((w) => /\.html?$/i.test(w.path));
}
