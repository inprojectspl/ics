/**
 * Title above the rendered markdown: the filename for collection sub-pages,
 * `docTitle` for single documents and the entry file (the storage filename
 * never changes, so a rename would not show otherwise).
 */
export function displayTitle(
  activePath: string,
  docTitle: string | null,
  entryPath?: string | null,
): string | null {
  if (!activePath) return docTitle;
  if (entryPath && activePath === entryPath) return docTitle;
  return activePath.split("/").pop()?.replace(/\.md$/i, "") || docTitle;
}
