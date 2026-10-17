import { useCallback, useEffect, useRef, useState } from "react";
import { clsx } from "clsx";
import "pdfjs-dist/web/pdf_viewer.css";
import "./pdfReader.css";
import { t, type MessageKey } from "../../lib/i18n";
import { useDrawerLock } from "../../lib/useDrawerLock";
import { loadErrorKey, MAX_CANVAS_PIXELS } from "./layout";
import { PdfToolbar, type FindState } from "./PdfToolbar";
import { loadPdfLibrary, openPdfDocument } from "./pdfjs";
import { useViewerGestures, type ScalableViewer } from "./useViewerGestures";

interface Props {
  /** Same-origin endpoint serving the PDF bytes (owner or share). */
  url: string;
  title?: string | null;
  downloadHref?: string;
}

// The state remembers the URL it belongs to, so a new URL reads as
// "loading" in render without resetting state from an effect.
type LoadState =
  | { url: string; status: "loading" }
  | { url: string; status: "error"; message: MessageKey }
  | { url: string; status: "ready"; pages: number };

/** What the handlers need from the pdf.js viewer (a subset, for tests). */
interface ReaderViewer extends ScalableViewer {
  currentPageNumber: number;
  currentScaleValue: string;
  increaseScale(): void;
  decreaseScale(): void;
}

interface Live {
  viewer: ReaderViewer;
  dispatch: (name: string, data: Record<string, unknown>) => void;
}

// Presets pdf.js recomputes on resize; a number is a zoom the reader chose.
const PRESETS = new Set(["auto", "page-width", "page-fit"]);
const IDLE_FIND: FindState = { query: "", current: 0, total: 0, notFound: false };

/**
 * PDF reader on pdf.js' viewer components (ADR-0022). No form, XFA or
 * scripting layer is mounted. The same element goes full screen, so the
 * document keeps its page and zoom when expanded.
 */
export function PdfReader({ url, title, downloadHref }: Props) {
  const [state, setState] = useState<LoadState>({ url, status: "loading" });
  const view: LoadState = state.url === url ? state : { url, status: "loading" };
  const [page, setPage] = useState(1);
  // Whole percent, the precision the toolbar shows: a pinch sends a scale
  // change per touch move, and equal values skip the render.
  const [zoom, setZoom] = useState(100);
  const [find, setFind] = useState<FindState>(IDLE_FIND);
  const [searchOpen, setSearchOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<HTMLDivElement>(null);
  const live = useRef<Live | null>(null);
  useViewerGestures(containerRef, live);

  useEffect(() => {
    let cancelled = false;
    let teardown = () => undefined as void;
    const handle = openPdfDocument(url);
    Promise.all([loadPdfLibrary(), handle.promise])
      .then(([{ pdfjs, viewer: V }, doc]) => {
        const container = containerRef.current;
        const inner = viewerRef.current;
        if (cancelled || !container || !inner) return;
        const eventBus = new V.EventBus();
        const linkService = new V.PDFLinkService({
          eventBus,
          externalLinkTarget: V.LinkTarget.BLANK,
          externalLinkRel: "noopener noreferrer nofollow",
        });
        const findController = new V.PDFFindController({ eventBus, linkService });
        const viewer = new V.PDFViewer({
          container,
          viewer: inner,
          eventBus,
          linkService,
          findController,
          removePageBorders: true,
          textLayerMode: 1,
          // Links and read-only annotations; form fields stay non-interactive.
          annotationMode: pdfjs.AnnotationMode.ENABLE,
          annotationEditorMode: pdfjs.AnnotationEditorType.DISABLE,
          maxCanvasPixels: MAX_CANVAS_PIXELS,
        });
        linkService.setViewer(viewer);
        eventBus.on("pagesinit", () => {
          viewer.currentScaleValue = "auto";
        });
        eventBus.on("pagechanging", (e: { pageNumber: number }) => setPage(e.pageNumber));
        eventBus.on("scalechanging", (e: { scale: number }) => setZoom(Math.round(e.scale * 100)));
        // pdf.js reports progress per page searched; unchanged counts keep the state.
        const onCount = (e: { matchesCount?: { current: number; total: number }; state?: number }) => {
          const { current, total } = e.matchesCount ?? { current: 0, total: 0 };
          const notFound = e.state === V.FindState.NOT_FOUND;
          setFind((f) =>
            f.current === current && f.total === total && f.notFound === notFound
              ? f
              : { ...f, current, total, notFound },
          );
        };
        eventBus.on("updatefindmatchescount", onCount);
        eventBus.on("updatefindcontrolstate", onCount);
        viewer.setDocument(doc);
        linkService.setDocument(doc, null);
        live.current = { viewer, dispatch: (name, data) => eventBus.dispatch(name, data) };
        setState({ url, status: "ready", pages: doc.numPages });
        teardown = () => {
          live.current = null;
          viewer.setDocument(null as never);
          linkService.setDocument(null, null);
        };
      })
      .catch((e: unknown) => {
        if (!cancelled) setState({ url, status: "error", message: loadErrorKey(e) });
      });
    return () => {
      cancelled = true;
      teardown();
      // Destroying the loading task also frees the document in the worker.
      handle.destroy().catch(() => undefined);
    };
  }, [url]);

  // A preset zoom (fit width, auto) follows the box: a resize, a rotated
  // phone, entering or leaving full screen.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      const v = live.current?.viewer;
      const preset = v?.currentScaleValue;
      // Setting the same preset again makes pdf.js recompute it for the new size.
      if (v && preset && PRESETS.has(preset)) v.currentScaleValue = preset;
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const onFind = useCallback((query: string, again?: "next" | "previous") => {
    setFind((f) => ({ ...f, query, notFound: false }));
    live.current?.dispatch("find", {
      source: null,
      type: again ? "again" : "",
      query,
      caseSensitive: false,
      entireWord: false,
      highlightAll: true,
      findPrevious: again === "previous",
      matchDiacritics: false,
    });
  }, []);

  const onSearchOpen = useCallback((open: boolean) => {
    setSearchOpen(open);
    if (!open) {
      setFind(IDLE_FIND);
      live.current?.dispatch("findbarclose", { source: null });
    }
  }, []);

  // Full screen: the page behind must not scroll and Esc closes it (the
  // search field keeps its own Esc). Ctrl/Cmd+F searches the PDF meanwhile.
  const collapse = useCallback(() => setExpanded(false), []);
  useDrawerLock(expanded, collapse);
  useEffect(() => {
    if (!expanded) return;
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f" && live.current) {
        e.preventDefault();
        setSearchOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [expanded]);

  const ready = view.status === "ready";
  return (
    <section
      aria-label={t("pdfView.reader")}
      className={clsx(
        "flex flex-col overflow-hidden bg-surface",
        expanded
          ? "fixed inset-0 z-50 h-dvh"
          : "h-[80dvh] min-h-[420px] rounded-control border border-border",
      )}
    >
      <PdfToolbar
        page={page}
        pages={ready ? view.pages : 0}
        zoom={zoom}
        disabled={!ready}
        onPage={(n) => {
          if (live.current) live.current.viewer.currentPageNumber = n;
        }}
        onZoomIn={() => live.current?.viewer.increaseScale()}
        onZoomOut={() => live.current?.viewer.decreaseScale()}
        onFitWidth={() => {
          if (live.current) live.current.viewer.currentScaleValue = "page-width";
        }}
        find={find}
        searchOpen={searchOpen}
        onSearchOpen={onSearchOpen}
        onFind={onFind}
        expanded={expanded}
        onExpand={setExpanded}
        title={title}
        downloadHref={downloadHref}
      />
      <div className="relative min-h-0 flex-1 bg-surface-subtle">
        {/* pdf.js requires an absolutely positioned scroll container. */}
        <div ref={containerRef} className="pdf-reader absolute inset-0 overflow-auto" tabIndex={0}>
          <div ref={viewerRef} className="pdfViewer" />
        </div>
        {view.status === "loading" && (
          <p
            className="absolute inset-x-0 top-12 text-center text-text-tertiary"
            role="status"
          >
            {t("pdfView.loading")}
          </p>
        )}
        {view.status === "error" && (
          <p className="absolute inset-x-0 top-12 px-4 text-center text-text-secondary" role="alert">
            {t(view.message)}
          </p>
        )}
      </div>
    </section>
  );
}
