import { FormEvent, useCallback, useEffect, useState, type ReactNode } from "react";
import { Download } from "lucide-react";
import { api, AssetDoc, ShareInfo } from "../api";
import { CenteredCard, Field, PrimaryButton } from "../components/Form";
import { HtmlBundleView } from "../components/HtmlBundleView";
import { OfficeDocument } from "../components/OfficeDocument";
import { OcrStatusView, PdfDocument } from "../components/PdfView";
import { VaultModeToggle, VaultReaderBody, type VaultMode } from "../components/VaultMode";
import { WithheldBlock } from "../components/ViewerStates";
import { CollectionFiles } from "../components/reader/CollectionFiles";
import { DocumentOutline } from "../components/reader/DocumentOutline";
import { readOutline, type OutlineEntry } from "../components/reader/outline";
import { ReaderLayout } from "../components/reader/ReaderLayout";
import { ReaderToolbar } from "../components/reader/ReaderToolbar";
import { useInspector } from "../components/reader/useInspector";
import { PageContext } from "../components/shell/PageContext";
import { buttonClass } from "../components/ui/Button";
import type { MenuAction } from "../components/ui/menuAction";
import { formatApiError } from "../lib/apiError";
import { displayTitle } from "../lib/displayTitle";
import { formatRelative } from "../lib/format";
import { t } from "../lib/i18n";
import { hasOcrState } from "../lib/ocr";
import { useCollectionDoc } from "../lib/useCollectionDoc";
import { useDocumentTitle } from "../lib/useDocumentTitle";
import { useTheme } from "../lib/theme";
import { useVersionPreview } from "../lib/useVersionPreview";
import { buildVaultBreadcrumbs } from "../lib/viewerPaths";
import { Viewer } from "./Viewer";

interface Props {
  token: string;
  /** `?ver=N`: read-only preview of an archived version. */
  version?: number;
  /** `?p=`: the file open in a collection. Needed because a role holder
   * gets the full reader at this address, and it navigates files via the
   * query string. */
  path?: string;
}

export function ShareView({ token, version, path }: Props) {
  const [info, setInfo] = useState<ShareInfo | null>(null);
  const [accessReady, setAccessReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [magicError, setMagicError] = useState<string | null>(null);

  const loadInfo = useCallback(
    () =>
      api.getShareInfo(token).then(
        (i) => {
          setInfo(i);
          setAccessReady(i.has_access);
        },
        (e) => setError(formatApiError(e)),
      ),
    [token],
  );

  // Auto-claim a magic-link token from ?m=... on first mount, then drop the
  // param from the URL so a refresh doesn't replay it (each token is
  // one-shot from the user's point of view; tampering with it after claim
  // is also harmless because session already has the verified flag).
  // `?ver=` stays in the URL: the version preview must survive the claim.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const m = params.get("m");
    if (!m) {
      void loadInfo();
      return;
    }
    (async () => {
      try {
        await api.shareMagicClaim(token, m);
      } catch (e) {
        setMagicError(formatApiError(e));
      } finally {
        params.delete("m");
        const clean = params.toString();
        window.history.replaceState({}, "", `/s/${token}${clean ? "?" + clean : ""}`);
        void loadInfo();
      }
    })();
  }, [token, loadInfo]);

  if (error) {
    return (
      <CenteredCard bare>
        <p className="mb-1 text-center text-meta font-medium text-text-secondary">
          {t("viewerStates.unavailable")}
        </p>
        <h1 className="mb-2 text-center text-title font-semibold text-text-primary [overflow-wrap:anywhere]">{t("shareView.brokenTitle")}</h1>
        <p className="text-text-secondary">{error}</p>
      </CenteredCard>
    );
  }

  if (!info) return <Loading />;

  if (info.requires_password) {
    return <PasswordGate token={token} title={info.title} onPass={loadInfo} />;
  }

  if (info.requires_magic_link) {
    return (
      <CenteredCard bare>
        <p className="mb-1 text-center text-meta font-medium text-text-secondary">
          {t("shareView.magicEyebrow")}
        </p>
        <h1 className="mb-2 text-center text-title font-semibold text-text-primary [overflow-wrap:anywhere]">
          {info.title || t("shareView.privateDoc")}
        </h1>
        <p className="text-text-secondary mb-6 text-center">
          {t("shareView.magicBody")}
        </p>
        {magicError && <p className="text-ui text-danger text-center">{magicError}</p>}
      </CenteredCard>
    );
  }

  if (info.requires_login) {
    return (
      <CenteredCard bare>
        <h1 className="mb-2 text-center text-title font-semibold text-text-primary [overflow-wrap:anywhere]">{t("shareView.loginTitle")}</h1>
        <p className="text-text-secondary mb-6 text-center">
          {t("shareView.loginBody")}
        </p>
        <div className="flex justify-center">
          <a href="/#login" className={buttonClass()}>
            {t("viewerStates.signIn")}
          </a>
        </div>
      </CenteredCard>
    );
  }

  // A team member opened a `/s/...` link from a colleague. They have a role
  // on the asset, so instead of the reduced visitor view we mount the full
  // reader at the same address (editing, history, no view counting).
  // The address stays `/s/<token>` because that is the link people share.
  if (info.my_role && info.slug) {
    return <Viewer slug={info.slug} path={path} version={version} basePath={`/s/${token}`} />;
  }

  // Info is loaded, no mode challenge applies, there is no role and the
  // link does not let the visitor in: a dead end, not a transient state.
  // This covers e.g. an `org_sso` link opened by a signed-in user outside
  // the allowed domain: they are signed in, so `requires_login` is false.
  if (!accessReady) return <NoLinkAccess title={info.title} />;

  return <ShareContent token={token} version={version} path={path} />;
}

// Module-level so the collection context keeps its identity across renders.
function shareHref(p: string): string {
  return `#p=${encodeURIComponent(p)}`;
}

function ShareContent({
  token,
  version,
  path,
}: {
  token: string;
  version?: number;
  /** `?p=` from the address. A visitor navigates the collection with hash
   * fragments, but may arrive via a link copied by the owner, whose reader
   * keeps the open file in the query string. */
  path?: string;
}) {
  const theme = useTheme();
  const [vaultMode, setVaultMode] = useState<VaultMode>("text");
  const [outline, setOutline] = useState<OutlineEntry[]>([]);
  const loadDoc = useCallback((): Promise<AssetDoc> => api.getShareDoc(token, version), [token, version]);
  const loadFile = useCallback((p: string) => api.getShareCollectionFile(token, p, version), [token, version]);
  const loadVersions = useCallback(() => api.getShareVersions(token), [token]);

  // Within a share, wikilinks stay inside the same token - pushState would
  // re-route into /v/... where auth/scope differs. Use hash fragments
  // intercepted by the wrapper below.
  const { doc, html, activePath, error, docErrorCode, openFile, collectionCtx } = useCollectionDoc({
    // The version is part of the document identity; otherwise `?ver=` would
    // change the URL while the hook kept the previous version's content.
    key: `${token}@${version ?? "current"}`,
    initialPath: path,
    loadDoc,
    loadFile,
    hrefFor: shareHref,
  });
  const inspector = useInspector(doc ? (doc.kind === "md_collection" ? "collection" : "document") : null);

  const { previewVersion, downloadHref, staleNotice, historyPanel } = useVersionPreview({
    doc,
    basePath: `/s/${token}`,
    loadVersions,
    downloadPath: `/api/share/${token}/download`,
  });
  useDocumentTitle(doc ? displayTitle(activePath, doc.title, doc.entry_path) || doc.slug : null);
  const onRendered = useCallback((root: HTMLElement) => setOutline(readOutline(root)), []);

  // A scanned document (office_doc) held for review: the backend refuses
  // the whole payload, so the notice stands in for the reader.
  if (docErrorCode === "bundle_withheld") return <WithheldBlock />;
  if (error)
    return (
      <CenteredCard bare>
        <p className="text-center text-text-secondary">{error}</p>
      </CenteredCard>
    );
  if (!doc) return <Loading />;

  const gated = doc.security_status === "critical" && !doc.security_bypass;
  const title = doc.title ?? doc.slug;
  const menu: MenuAction[] =
    downloadHref && !gated
      ? [{ key: "download", label: t("reader.download"), icon: Download, onClick: () => window.location.assign(downloadHref) }]
      : [];
  const inspectorToggle = {
    open: inspector.open,
    toggle: () => inspector.setOpen(!inspector.open),
    label: t(inspector.open ? "reader.inspectorHide" : "reader.inspectorShow"),
  };
  const toolbar = (start: ReactNode) => (
    <ReaderToolbar start={start} menu={menu} menuLabel={t("documentRow.actions", { title })} inspector={inspectorToggle} />
  );
  const facts = <span className="truncate">{t("assetRow.changed", { when: formatRelative(doc.version_created_at ?? doc.updated_at) })}</span>;
  const closeIfDrawer = () => {
    if (!window.matchMedia("(min-width: 1280px)").matches) inspector.setOpen(false);
  };

  if (doc.kind === "html_bundle" || doc.kind === "pdf_doc" || doc.kind === "office_doc") {
    return (
      <>
        <PageContext crumbs={[{ label: title }]} />
        <ReaderLayout banner={staleNotice} toolbar={toolbar(facts)} inspector={inspector} panels={{ history: historyPanel }}>
          {doc.kind === "html_bundle" ? (
            <HtmlBundleView
              title={doc.title}
              entryPath={doc.entry_path}
              sizeBytes={doc.size_bytes}
              accessGated={gated}
              previewVersion={previewVersion}
              fetchGrantUrl={async () => (await api.getShareHtmlGrant(token, previewVersion ?? undefined)).url}
              downloadHref={gated ? undefined : downloadHref}
            />
          ) : doc.kind === "pdf_doc" ? (
            <PdfDocument
              url={api.sharePdfUrl(token, previewVersion ?? undefined)}
              title={doc.title}
              info={doc.pdf}
              downloadHref={downloadHref}
              accessGated={gated}
              ocr={hasOcrState(doc.ocr) ? <OcrStatusView state={doc.ocr} pageCount={doc.pdf?.page_count} /> : undefined}
            />
          ) : (
            <OfficeDocument
              html={html}
              theme={theme}
              title={doc.title}
              info={doc.document}
              downloadHref={downloadHref}
              accessGated={gated}
            />
          )}
        </ReaderLayout>
      </>
    );
  }

  const docTitle = displayTitle(activePath, doc.title, doc.entry_path);
  const isVault = doc.kind === "md_collection";
  const showGraph = isVault && vaultMode === "graph";
  const pick = (p: string) => {
    setVaultMode("text");
    openFile(p);
  };

  return (
    <div
      className="flex min-h-0 flex-1 flex-col"
      onClick={(e) => {
        const a = (e.target as HTMLElement).closest("a.wikilink") as HTMLAnchorElement | null;
        if (!a) return;
        const m = (a.getAttribute("href") || "").match(/^#p=(.+)$/);
        if (!m?.[1]) return;
        e.preventDefault();
        pick(decodeURIComponent(m[1]));
      }}
    >
      <PageContext crumbs={isVault ? (buildVaultBreadcrumbs(doc.title || doc.slug, activePath) ?? [{ label: title }]) : [{ label: title }]} />
      <ReaderLayout
        banner={staleNotice}
        toolbar={toolbar(isVault ? <VaultModeToggle mode={vaultMode} onChange={setVaultMode} /> : facts)}
        inspector={inspector}
        panels={{
          files: collectionCtx ? (
            <CollectionFiles
              tree={collectionCtx.paths}
              currentPath={activePath}
              onSelect={(p) => {
                pick(p);
                closeIfDrawer();
              }}
              downloadHref={downloadHref}
            />
          ) : undefined,
          outline: showGraph ? undefined : <DocumentOutline entries={outline} onJump={closeIfDrawer} />,
          history: historyPanel,
        }}
      >
        <VaultReaderBody
          graph={showGraph ? { source: `share:${token}`, fetcher: () => api.getShareGraph(token) } : null}
          activePath={activePath}
          onOpenFile={openFile}
          onModeChange={setVaultMode}
          markdown={{ html, theme, title: docTitle, collection: collectionCtx, onRendered }}
          downloadHref={undefined}
        >
          {null}
        </VaultReaderBody>
      </ReaderLayout>
    </div>
  );
}

/** The link exists and is active, but does not admit this visitor and
 * offers them no challenge to pass. */
function NoLinkAccess({ title }: { title: string | null }) {
  return (
    <CenteredCard bare>
      <p className="mb-1 text-center text-meta font-medium text-text-secondary">
        {t("viewerStates.noAccess")}
      </p>
      <h1 className="mb-2 text-center text-title font-semibold text-text-primary [overflow-wrap:anywhere]">
        {title || t("shareView.privateDoc")}
      </h1>
      <p className="text-text-secondary text-center">
        {t("shareView.noLinkAccessBody")}
      </p>
    </CenteredCard>
  );
}

function Loading() {
  return (
    <div role="status" className="flex min-h-[50dvh] flex-1 items-center justify-center text-ui text-text-secondary">
      {t("app.loading")}
    </div>
  );
}

function PasswordGate({
  token,
  title,
  onPass,
}: {
  token: string;
  title: string | null;
  onPass: () => void;
}) {
  const [pwd, setPwd] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      await api.shareAuth(token, pwd);
      onPass();
    } catch {
      setErr(t("shareView.wrongPassword"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <CenteredCard bare>
      <p className="mb-1 text-center text-meta font-medium text-text-secondary">
        {t("shareView.passwordEyebrow")}
      </p>
      <h1 className="mb-2 text-center text-title font-semibold text-text-primary [overflow-wrap:anywhere]">
        {title || t("shareView.passwordTitle")}
      </h1>
      <form onSubmit={submit} className="space-y-4">
        <Field label={t("common.password")} type="password" value={pwd} onChange={setPwd} autoComplete="off" />
        {err && <p className="text-ui text-danger">{err}</p>}
        <PrimaryButton type="submit" busy={busy}>
          {busy ? t("shareView.checking") : t("common.open")}
        </PrimaryButton>
      </form>
    </CenteredCard>
  );
}
