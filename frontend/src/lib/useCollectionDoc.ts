/**
 * Loaded doc, current file html and active path for the viewer and the share
 * viewer. The doc is fetched per `key`, sub-files per path. `reload()`
 * resolves only once doc and active file are settled, so callers can await it
 * before opening the editor.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { AssetDoc, CollectionFile } from "../api";
import { errorCode, formatApiError, statusCode } from "./apiError";
import type { CollectionContext } from "./hydrateMarkdown";

export interface UseCollectionDocOpts {
  key: string; // identity of the doc source (slug or share token)
  initialPath?: string;
  loadDoc: () => Promise<AssetDoc>;
  loadFile: (path: string) => Promise<CollectionFile>;
  hrefFor: (path: string) => string;
  onNavigate?: (path: string) => void; // for URL syncing
}

export interface ReloadOpts {
  /** When set, after re-fetching the doc the hook navigates to this
   * path (loading its html). When omitted, the current activePath is
   * preserved if still present in the new tree; otherwise it falls
   * back to the doc's entry_path. */
  activeAfter?: string;
}

export interface UseCollectionDocResult {
  doc: AssetDoc | null;
  html: string;
  activePath: string;
  error: string | null;
  /** HTTP status of a failed read of the document itself, for the entry
   * resolver. A failed collection file read leaves it `null`: a 404 of one
   * file must not show the owner a "no access" wall. */
  docErrorStatus: number | null;
  /** Server `code` of the same failure, e.g. `bundle_withheld` for a
   * document held for review. */
  docErrorCode: string | null;
  openFile: (target: string) => void;
  reload: (opts?: ReloadOpts) => Promise<void>;
  collectionCtx: CollectionContext | null;
}

export function useCollectionDoc({
  key,
  initialPath,
  loadDoc,
  loadFile,
  hrefFor,
  onNavigate,
}: UseCollectionDocOpts): UseCollectionDocResult {
  const [doc, setDoc] = useState<AssetDoc | null>(null);
  const [html, setHtml] = useState("");
  const [activePath, setActivePath] = useState(initialPath ?? "");
  const [error, setError] = useState<string | null>(null);
  // The failed document read itself (null when the doc loaded, or only a
  // single file failed); status and code are derived from it.
  const [docFailure, setDocFailure] = useState<unknown>(null);

  // Single place to record an error so message and status never diverge.
  // `scope` tells whether the document failed (then the status matters to
  // the entry resolver) or a single file in the collection.
  const fail = useCallback((e: unknown, scope: "doc" | "file" = "doc") => {
    setError(e === null ? null : formatApiError(e));
    setDocFailure(scope === "doc" ? e : null);
  }, []);

  // Ref mirror so `reload()` has a stable identity (deps = [loadDoc,
  // loadFile]) but still reads the latest activePath when invoked.
  const activePathRef = useRef(activePath);
  activePathRef.current = activePath;

  // Fetch the doc once per key (slug/token), independently of path changes.
  useEffect(() => {
    let cancelled = false;
    setDoc(null);
    fail(null);
    loadDoc()
      .then(async (d) => {
        if (cancelled) return;
        setDoc(d);
        const target = initialPath || d.entry_path || "";
        setActivePath(target);
        if (!target || target === d.entry_path) {
          setHtml(d.html);
          return;
        }
        // A deep link to a non-entry file: the path effect below sees
        // `initialPath === activePath` and bails out, so fetch it here.
        if (d.kind !== "md_collection") return;
        try {
          const f = await loadFile(target);
          if (cancelled) return;
          setActivePath(f.path);
          setHtml(f.html);
        } catch (e) {
          if (!cancelled) fail(e, "file");
        }
      })
      .catch((e) => !cancelled && fail(e));
    return () => {
      cancelled = true;
    };
    // Keyed on the doc identity only: re-running when the loaders or the
    // initial path change would refetch the whole doc on every navigation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  // When the initial-path prop changes externally (e.g. browser back/forward
  // updates the URL) and we already have the doc loaded, fetch that file.
  useEffect(() => {
    if (!doc || doc.kind !== "md_collection") return;
    if (!initialPath || initialPath === activePath) return;
    let cancelled = false;
    if (initialPath === doc.entry_path) {
      setActivePath(initialPath);
      setHtml(doc.html);
      return;
    }
    loadFile(initialPath)
      .then((f) => {
        if (cancelled) return;
        setActivePath(f.path);
        setHtml(f.html);
      })
      .catch((e) => !cancelled && fail(e, "file"));
    return () => {
      cancelled = true;
    };
    // activePath is written by this effect, so depending on it would loop;
    // loadFile and fail are stable for the lifetime of a doc.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialPath, doc]);

  const openFile = useCallback(
    (target: string) => {
      if (!doc || doc.kind !== "md_collection") return;
      if (target === activePath) return;
      onNavigate?.(target);
      if (target === doc.entry_path) {
        setActivePath(target);
        setHtml(doc.html);
        return;
      }
      loadFile(target)
        .then((f) => {
          setActivePath(f.path);
          setHtml(f.html);
        })
        .catch((e) => fail(e, "file"));
    },
    [doc, activePath, loadFile, onNavigate, fail],
  );

  const reload = useCallback(
    async (opts: ReloadOpts = {}): Promise<void> => {
      try {
        const fresh = await loadDoc();
        setDoc(fresh);
        fail(null);

        if (fresh.kind !== "md_collection") {
          setHtml(fresh.html || "");
          return;
        }

        const currentActive = activePathRef.current;
        const treeSet = new Set(fresh.tree || []);
        const desired =
          opts.activeAfter
            ?? (currentActive && treeSet.has(currentActive)
              ? currentActive
              : fresh.entry_path)
            ?? "";

        if (!desired) {
          setActivePath("");
          setHtml(fresh.html || "");
          return;
        }
        if (desired === fresh.entry_path) {
          setActivePath(desired);
          setHtml(fresh.html);
          return;
        }
        try {
          const f = await loadFile(desired);
          setActivePath(f.path);
          setHtml(f.html);
        } catch (e) {
          // The requested file vanished between mutation and reload -
          // fall back to the fresh entry rather than wedging the view.
          if (fresh.entry_path) {
            setActivePath(fresh.entry_path);
            setHtml(fresh.html);
          } else {
            fail(e, "file");
          }
        }
      } catch (e) {
        fail(e);
      }
    },
    [loadDoc, loadFile, fail],
  );

  // MarkdownView re-hydrates whenever this identity changes, so it must stay
  // stable across unrelated re-renders of the page.
  const tree = doc?.kind === "md_collection" ? doc.tree : undefined;
  const collectionCtx = useMemo<CollectionContext | null>(
    () => (tree ? { paths: tree, current: activePath, hrefFor } : null),
    [tree, activePath, hrefFor],
  );

  const docErrorStatus = docFailure === null ? null : statusCode(docFailure);
  const docErrorCode = docFailure === null ? null : errorCode(docFailure);

  return {
    doc,
    html,
    activePath,
    error,
    docErrorStatus,
    docErrorCode,
    openFile,
    reload,
    collectionCtx,
  };
}
