import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { api, type AssetDoc } from "../api";
import { HtmlBundleView } from "../components/HtmlBundleView";
import { InlineEditor } from "../components/InlineEditor";
import { NewFileDialog } from "../components/NewFileDialog";
import { OfficeDocument } from "../components/OfficeDocument";
import { LiveOcrStatus, PdfDocument } from "../components/PdfView";
import { RelationsInspector, RelationsView } from "../components/RelationsPanel";
import { VaultModeToggle, VaultReaderBody, type VaultMode } from "../components/VaultMode";
import { AssetWatchToggle } from "../components/WatchToggle";
import { ErrorBlock, Loading, NoAccessBlock, WithheldBlock } from "../components/ViewerStates";
import { KindIcon } from "../components/documents/kindIcon";
import { CollectionFiles } from "../components/reader/CollectionFiles";
import { DocumentOutline } from "../components/reader/DocumentOutline";
import { readOutline, type OutlineEntry } from "../components/reader/outline";
import { ReaderDetails } from "../components/reader/ReaderDetails";
import { ReaderLayout, type InspectorTab } from "../components/reader/ReaderLayout";
import { ReaderToolbar } from "../components/reader/ReaderToolbar";
import { useInspector } from "../components/reader/useInspector";
import { useReaderActions } from "../components/reader/useReaderActions";
import { PageContext, type Crumb } from "../components/shell/PageContext";
import { useShell } from "../components/shell/shellContext";
import { agentViewHref } from "../lib/agentView";
import { canEdit } from "../lib/assetRoles";
import { graphHref } from "../lib/graphHref";
import { displayTitle } from "../lib/displayTitle";
import { formatRelative } from "../lib/format";
import { t } from "../lib/i18n";
import { hasOcrState } from "../lib/ocr";
import { useCollectionDoc } from "../lib/useCollectionDoc";
import { useDocumentTitle } from "../lib/useDocumentTitle";
import { useEntryFallback } from "../lib/useEntryFallback";
import { useSessionUser } from "../lib/useSessionUser";
import { useTheme } from "../lib/theme";
import { useVaultFileActions } from "../lib/useVaultFileActions";
import { useVersionPreview } from "../lib/useVersionPreview";
import { buildVaultBreadcrumbs, canonicalPath, inferDefaultFolder } from "../lib/viewerPaths";

interface Props {
  slug: string;
  path?: string;
  /** `?ver=N`: read-only preview of an archived version. */
  version?: number;
  /** The path this view is mounted under, `/v/<slug>` by default.
   * ShareView mounts the same reader under `/s/<token>` for someone with a
   * role on the asset, and then file navigation must stay within the token
   * instead of jumping to the internal address. */
  basePath?: string;
  /** `?tab=relations`: the document's relations instead of its content. */
  tab?: "relations";
}

const DOCKED = "(min-width: 1280px)";

/** Closes the inspector drawer after a pick; a docked panel stays. */
function closeIfDrawer(close: () => void) {
  if (!window.matchMedia(DOCKED).matches) close();
}

export function Viewer({ slug, path, version, basePath, tab }: Props) {
  const theme = useTheme();
  const [editing, setEditing] = useState(false);
  const [vaultMode, setVaultMode] = useState<VaultMode>("text");
  const [outline, setOutline] = useState<OutlineEntry[]>([]);
  const { setFocusMode } = useShell();
  // Reading focus belongs to this page; leaving it gives the sidebar back.
  useEffect(() => () => setFocusMode(false), [setFocusMode]);

  const loadDoc = useCallback(() => api.getDoc(slug, version), [slug, version]);
  const loadFile = useCallback((p: string) => api.getCollectionFile(slug, p, version), [slug, version]);
  // Links inside the reader (wikilinks, tree, breadcrumbs, version preview)
  // must keep the address the reader was opened under and carry `?ver=`,
  // or the first click would leave `/s/<token>` or the preview. A ref,
  // because the canonical address arrives with the document while `hrefFor`
  // is needed earlier; synced in a layout effect, before MarkdownView
  // hydrates links.
  const baseRef = useRef(basePath ?? `/v/${slug}`);
  const pathHref = useCallback(
    (p: string) => `${baseRef.current}?p=${encodeURIComponent(p)}${version ? `&ver=${version}` : ""}`,
    [version],
  );
  const onNavigate = useCallback((p: string) => window.history.pushState({}, "", pathHref(p)), [pathHref]);
  const { doc, html, activePath, error, docErrorStatus, docErrorCode, openFile, reload, collectionCtx } =
    useCollectionDoc({
      // A version change is a different document for the hook.
      key: `${slug}@${version ?? "current"}`,
      initialPath: path,
      loadDoc,
      loadFile,
      hrefFor: pathHref,
      onNavigate,
    });
  // `/doc` requires a session, so a loaded document is the signal to ask
  // who is signed in; a link visitor on a dead end never triggers a 401.
  const me = useSessionUser(Boolean(doc));
  const inspector = useInspector(doc ? (doc.kind === "md_collection" ? "collection" : "document") : null);

  const onEnterEditor = useCallback(() => setEditing(true), []);
  const {
    fileInputRef,
    newFileOpen,
    setNewFileOpen,
    openFilePicker,
    onPickedFile,
    onCreateEmptyFile,
    onDeleteFile,
    onMoveFile,
  } = useVaultFileActions({ assetId: doc?.id ?? "", activePath, reload, onEnterEditor });
  const assetId = doc?.id;
  const loadVersions = useCallback(() => (assetId ? api.listVersions(assetId) : Promise.resolve([])), [assetId]);
  const entryState = useEntryFallback(slug, docErrorStatus);
  const base = basePath ?? canonicalPath(doc?.canonical_url) ?? `/v/${slug}`;
  useLayoutEffect(() => {
    baseRef.current = base;
  }, [base]);
  // People paste the address bar into team chat, so it must show an
  // address that works for the recipient. Only `replaceState` and only on
  // `/v/`; the anchor (`#setup`) is kept.
  const canonical = basePath ? undefined : canonicalPath(doc?.canonical_url);
  useEffect(() => {
    if (!canonical || canonical === window.location.pathname) return;
    window.history.replaceState({}, "", canonical + window.location.search + window.location.hash);
  }, [canonical]);

  const { previewVersion, downloadHref, staleNotice, historyPanel } = useVersionPreview({
    doc,
    basePath: base,
    loadVersions,
    downloadPath: `/api/assets/by-slug/${slug}/download`,
  });
  useDocumentTitle(doc ? displayTitle(activePath, doc.title, doc.entry_path) || doc.slug : null);

  const reader = useReaderActions({
    slug,
    role: doc?.my_role,
    previewVersion,
    reload,
    downloadHref,
    relationsHref: tab === "relations" ? undefined : `${base}?tab=relations`,
  });
  const onRendered = useCallback((root: HTMLElement) => setOutline(readOutline(root)), []);

  if (error || !doc) {
    return (
      <>
        <PageContext crumbs={[{ label: t("nav.documents"), href: "/" }]} />
        {!error ? (
          <Loading />
        ) : docErrorCode === "bundle_withheld" ? (
          // A read-only role on a document held for review (office_doc).
          <WithheldBlock />
        ) : entryState === "resolving" ? (
          // 401/404 is not a dead end yet: the resolver looks for a way in.
          <Loading />
        ) : entryState === "dead-end" ? (
          <NoAccessBlock />
        ) : (
          <ErrorBlock message={error} />
        )}
      </>
    );
  }

  const title = doc.title ?? doc.slug;
  // A document in a project sits under it, one click from the project.
  const trail: Crumb[] = reader.project
    ? [
        { label: t("nav.projects"), href: "/projects" },
        { label: reader.project.name, href: `/projects/${reader.project.slug}` },
      ]
    : [{ label: t("nav.documents"), href: "/" }];
  const context = (crumbs: Crumb[]) => (
    <PageContext
      crumbs={[...trail, ...crumbs]}
      activeHref={reader.project ? `/projects/${reader.project.slug}` : null}
      actions={me ? <AssetWatchToggle assetId={doc.id} projectName={reader.project?.name ?? null} /> : undefined}
    />
  );

  const menuLabel = t("documentRow.actions", { title });
  const details = reader.asset ? (
    <ReaderDetails asset={reader.asset} project={reader.project} onChanged={reader.onChanged} onAssignProject={reader.assignProject} />
  ) : undefined;
  const inspectorToggle = {
    open: inspector.open,
    toggle: () => inspector.setOpen(!inspector.open),
    label: t(inspector.open ? "reader.inspectorHide" : "reader.inspectorShow"),
  };
  const facts = <DocFacts doc={doc} />;
  const relations = reader.asset ? (
    <RelationsInspector slug={reader.asset.slug} assetId={reader.asset.id} canEdit={canEdit(reader.asset)} />
  ) : undefined;
  // Who may see the document's relations may walk them in the graph view too.
  const graph = reader.asset ? graphHref(reader.asset.slug) : undefined;
  const panelsFor = (extra: Partial<Record<InspectorTab, ReactNode>>) => ({ ...extra, details, relations, history: historyPanel });

  if (tab === "relations") {
    return (
      <>
        {context([{ label: title, href: base }, { label: t("relations.title") }])}
        <ReaderLayout
          toolbar={
            <ReaderToolbar
              start={facts}
              menu={reader.menu}
              menuLabel={menuLabel}
              onShare={reader.share ?? undefined}
              inspector={details ? inspectorToggle : undefined}
              graphHref={graph}
            />
          }
          inspector={inspector}
          panels={{ details }}
        >
          <RelationsView
            slug={slug}
            assetId={doc.id}
            title={title}
            canEdit={doc.my_role !== undefined && doc.my_role !== "viewer"}
            documentHref={base}
          />
        </ReaderLayout>
        {reader.dialogs}
      </>
    );
  }

  const security = {
    securityStatus: doc.security_status,
    securityReport: doc.security_report,
    securityBypass: doc.security_bypass,
  };

  if (doc.kind === "html_bundle" || doc.kind === "pdf_doc" || doc.kind === "office_doc") {
    let body: ReactNode;
    if (doc.kind === "html_bundle") {
      body = (
        <HtmlBundleView
          title={doc.title}
          entryPath={doc.entry_path}
          sizeBytes={doc.size_bytes}
          files={doc.files}
          {...security}
          previewVersion={previewVersion}
          fetchGrantUrl={async () => (await api.getAssetHtmlGrant(slug, previewVersion ?? undefined)).url}
          downloadHref={downloadHref}
        />
      );
    } else if (doc.kind === "pdf_doc") {
      body = (
        <PdfDocument
          url={api.pdfUrl(slug, previewVersion ?? undefined)}
          title={doc.title}
          info={doc.pdf}
          downloadHref={downloadHref}
          ocr={
            hasOcrState(doc.ocr) ? (
              <LiveOcrStatus
                slug={slug}
                assetId={doc.id}
                version={previewVersion ?? undefined}
                initial={doc.ocr}
                pageCount={doc.pdf?.page_count}
                // Runs belong to the current version; an archived preview is read-only.
                canRequest={previewVersion === null && doc.my_role !== "viewer"}
                textHref={doc.my_role !== "viewer" ? agentViewHref(slug, { version: previewVersion ?? undefined }) : null}
              />
            ) : undefined
          }
          {...security}
        />
      );
    } else {
      body = (
        <OfficeDocument html={html} theme={theme} title={doc.title} info={doc.document} downloadHref={downloadHref} {...security} />
      );
    }
    return (
      <>
        {context([{ label: title }])}
        <ReaderLayout
          banner={staleNotice}
          toolbar={
            <ReaderToolbar
              start={facts}
              menu={reader.menu}
              menuLabel={menuLabel}
              onShare={reader.share ?? undefined}
              inspector={inspectorToggle}
              graphHref={graph}
            />
          }
          inspector={inspector}
          panels={panelsFor({})}
        >
          {body}
        </ReaderLayout>
        {reader.dialogs}
      </>
    );
  }

  const docTitle = displayTitle(activePath, doc.title, doc.entry_path);
  // A read-only role gets no edit action (the API would refuse it too), and
  // an archived preview never: the editor saves to the current version, so
  // "edit v1" would overwrite v5. Old content comes back through restore.
  const editable =
    previewVersion === null && (doc.kind === "md_single" || doc.kind === "md_collection") && doc.my_role !== "viewer";
  // A collection edits the file in view; a single document has no path.
  const editPath = doc.kind === "md_collection" ? activePath : undefined;
  const isVault = doc.kind === "md_collection";
  const showGraph = isVault && vaultMode === "graph";
  const vaultCrumbs = isVault
    ? buildVaultBreadcrumbs(doc.title || doc.slug, activePath, `${base}${previewVersion ? `?ver=${previewVersion}` : ""}`)
    : undefined;
  const crumbs = vaultCrumbs ?? [{ label: title }];

  if (editing && editable) {
    return (
      <>
        {context(crumbs)}
        <InlineEditor
          assetId={doc.id}
          slug={slug}
          path={editPath}
          onCancel={() => setEditing(false)}
          onSaved={async () => {
            setEditing(false);
            await reload();
          }}
        />
      </>
    );
  }

  const pick = (p: string) => {
    // A file from the tree always opens as text: the user wants that file.
    setVaultMode("text");
    openFile(p);
  };

  return (
    <div
      className="flex min-h-0 flex-1 flex-col"
      onClick={(e) => {
        // Wikilinks stay in the app: their `?p=` href would reload the page.
        const a = (e.target as HTMLElement).closest("a.wikilink") as HTMLAnchorElement | null;
        if (!a) return;
        const m = (a.getAttribute("href") || "").match(/[?&]p=([^&#]+)/);
        if (!m?.[1]) return;
        e.preventDefault();
        pick(decodeURIComponent(m[1]));
      }}
    >
      {context(crumbs)}
      <ReaderLayout
        banner={staleNotice}
        toolbar={
          <ReaderToolbar
            start={isVault ? <VaultModeToggle mode={vaultMode} onChange={setVaultMode} /> : facts}
            onEdit={editable && !showGraph ? () => setEditing(true) : undefined}
            onShare={reader.share ?? undefined}
            menu={reader.menu}
            menuLabel={menuLabel}
            inspector={inspectorToggle}
            graphHref={graph}
          />
        }
        inspector={inspector}
        panels={panelsFor({
          files: collectionCtx ? (
            <CollectionFiles
              tree={collectionCtx.paths}
              currentPath={activePath}
              onSelect={(p) => {
                pick(p);
                closeIfDrawer(() => inspector.setOpen(false));
              }}
              onCreateFile={editable ? () => setNewFileOpen(true) : undefined}
              onUploadFile={editable ? openFilePicker : undefined}
              onDeleteFile={editable ? onDeleteFile : undefined}
              onMoveFile={editable ? onMoveFile : undefined}
              downloadHref={downloadHref}
            />
          ) : undefined,
          outline: showGraph ? undefined : (
            <DocumentOutline entries={outline} onJump={() => closeIfDrawer(() => inspector.setOpen(false))} />
          ),
        })}
      >
        <VaultReaderBody
          graph={showGraph ? { source: `owner:${slug}`, fetcher: () => api.getGraph(slug) } : null}
          activePath={activePath}
          onOpenFile={openFile}
          onModeChange={setVaultMode}
          markdown={{ html, theme, title: docTitle, collection: collectionCtx, onRendered }}
          downloadHref={undefined}
        >
          {null}
        </VaultReaderBody>
      </ReaderLayout>
      {reader.dialogs}
      <input
        ref={fileInputRef}
        type="file"
        accept=".md"
        className="sr-only"
        tabIndex={-1}
        aria-hidden
        onChange={async (e) => {
          // currentTarget is null once the handler yields at await.
          const input = e.currentTarget;
          await onPickedFile(input.files);
          input.value = "";
        }}
      />
      {newFileOpen && collectionCtx && (
        <NewFileDialog
          existing={collectionCtx.paths}
          defaultFolder={inferDefaultFolder(activePath, collectionCtx.paths)}
          onClose={() => setNewFileOpen(false)}
          onCreate={onCreateEmptyFile}
        />
      )}
    </div>
  );
}

/** Left end of the reader toolbar: what is open and how fresh it is. */
function DocFacts({ doc }: { doc: AssetDoc }) {
  const version = doc.preview_version ?? doc.version;
  const changed = doc.preview_version ? (doc.version_created_at ?? doc.updated_at) : doc.updated_at;
  return (
    <span className="flex min-w-0 items-center gap-2">
      <KindIcon kind={doc.kind} size={16} aria-hidden className="shrink-0" />
      <span className="tabular-nums">v{version}</span>
      <span aria-hidden className="text-text-tertiary">
        ·
      </span>
      <span className="truncate">{t("assetRow.changed", { when: formatRelative(changed) })}</span>
    </span>
  );
}
