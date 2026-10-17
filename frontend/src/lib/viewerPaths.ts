import type { Crumb as BreadcrumbSegment } from "../components/shell/PageContext";

/** Breadcrumbs `<collection> / <folder> / … / <filename>` for a vault file.
 * Only the collection links (to `rootHref`, absent for share visitors);
 * folders are not navigable. `undefined` while there is no activePath. */
export function buildVaultBreadcrumbs(
  collectionLabel: string,
  activePath: string,
  rootHref?: string,
): BreadcrumbSegment[] | undefined {
  if (!activePath) return undefined;
  const parts = activePath.split("/").filter(Boolean);
  if (parts.length === 0) return undefined;
  const fileName = (parts.at(-1) ?? "").replace(/\.md$/i, "");
  const folders = parts.slice(0, -1);
  return [
    rootHref ? { label: collectionLabel, href: rootHref } : { label: collectionLabel },
    ...folders.map((f) => ({ label: f })),
    { label: fileName },
  ];
}

/** Default folder for "New file": the current file's folder, else the
 * collection's only top-level folder (a vault uploaded as one directory),
 * else the root. */
export function inferDefaultFolder(activePath: string, paths: string[]): string {
  const slash = activePath.lastIndexOf("/");
  if (slash > 0) return activePath.slice(0, slash);

  const topFolders = new Set<string>();
  for (const p of paths) {
    const i = p.indexOf("/");
    if (i > 0) topFolders.add(p.slice(0, i));
  }
  return topFolders.size === 1 ? Array.from(topFolders)[0] ?? "" : "";
}

/** Same-origin path from `canonical_url`, or `undefined` when the backend
 * returned something outside this instance. */
export function canonicalPath(url: string | undefined): string | undefined {
  if (!url) return undefined;
  const target = new URL(url, window.location.origin);
  return target.origin === window.location.origin ? target.pathname : undefined;
}
