/**
 * The only module that touches pdfjs-dist. The library and its viewer
 * components (~1.3 MB with the worker) are imported dynamically, so they land
 * in chunks only a PDF reader downloads. Components depend on this module's
 * functions, which keeps them testable with a mocked loader.
 */
import type { PDFDocumentLoadingTask, PDFDocumentProxy } from "pdfjs-dist";
// `?worker&url` bundles the worker as a `.js` chunk: servers map `.mjs` to
// octet-stream often enough to break a module worker.
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?worker&url";

type Pdfjs = typeof import("pdfjs-dist");
type PdfViewerModule = typeof import("pdfjs-dist/web/pdf_viewer.mjs");

export interface PdfLibrary {
  pdfjs: Pdfjs;
  viewer: PdfViewerModule;
}

let libraryPromise: Promise<PdfLibrary> | null = null;

/** pdf.js and its viewer components, loaded once per tab. */
export function loadPdfLibrary(): Promise<PdfLibrary> {
  libraryPromise ??= import("pdfjs-dist").then(
    async (pdfjs) => {
      pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
      // The viewer module reads the library from this global (pdf.js 4+).
      (globalThis as { pdfjsLib?: Pdfjs }).pdfjsLib = pdfjs;
      const viewer = await import("pdfjs-dist/web/pdf_viewer.mjs");
      return { pdfjs, viewer };
    },
    (e: unknown) => {
      // A failed chunk fetch (deploy in between, flaky network) must not
      // poison every later attempt in this tab.
      libraryPromise = null;
      throw e;
    },
  );
  return libraryPromise;
}

/** Where the build serves pdf.js run-time files (see `pdfjsAssets` in
 * vite.config.ts): decoders for JBIG2 and JPEG 2000 scans, colour profiles,
 * CMaps for CJK fonts and the 14 standard fonts. */
function assetBase(version: string): string {
  return `/pdfjs/${version}/`;
}

export interface PdfHandle {
  promise: Promise<PDFDocumentProxy>;
  /** Aborts the download and frees the worker-side document. Safe to call
   * before the library has loaded. */
  destroy: () => Promise<void>;
}

/** Thrown into `promise` when `destroy` ran before loading started. */
export class PdfLoadAborted extends Error {
  constructor() {
    super("PDF loading aborted");
    this.name = "PdfLoadAborted";
  }
}

export function openPdfDocument(url: string): PdfHandle {
  let task: PDFDocumentLoadingTask | null = null;
  let destroyed = false;
  const promise = loadPdfLibrary().then(({ pdfjs }) => {
    if (destroyed) throw new PdfLoadAborted();
    const base = assetBase(pdfjs.version);
    task = pdfjs.getDocument({
      url,
      // The owner and share endpoints authenticate with cookies.
      withCredentials: true,
      // XFA forms would be rendered as HTML into the page. pdf.js 6 never
      // evaluates code and runs no document JavaScript without the scripting
      // manager, which the reader does not mount.
      enableXfa: false,
      wasmUrl: `${base}wasm/`,
      iccUrl: `${base}iccs/`,
      cMapUrl: `${base}cmaps/`,
      cMapPacked: true,
      standardFontDataUrl: `${base}standard_fonts/`,
    });
    return task.promise;
  });
  return {
    promise,
    destroy: async () => {
      destroyed = true;
      await task?.destroy();
    },
  };
}
