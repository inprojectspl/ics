import { afterEach, describe, expect, it, vi } from "vitest";

const destroy = vi.fn(async () => undefined);
const getDocument = vi.fn(() => ({ promise: Promise.resolve({ numPages: 1 }), destroy }));
const GlobalWorkerOptions = { workerSrc: "" };

vi.mock("pdfjs-dist", () => ({ getDocument, GlobalWorkerOptions, version: "6.3.289" }));
vi.mock("pdfjs-dist/web/pdf_viewer.mjs", () => ({ PDFViewer: class {} }));
vi.mock("pdfjs-dist/build/pdf.worker.min.mjs?worker&url", () => ({ default: "/assets/pdf.worker.js" }));

const { loadPdfLibrary, openPdfDocument, PdfLoadAborted } = await import("./pdfjs");

afterEach(() => vi.clearAllMocks());

describe("openPdfDocument", () => {
  it("opens the URL with cookies, without XFA and with the run-time files, after pointing pdf.js at the worker", async () => {
    const handle = openPdfDocument("/api/share/t/pdf");
    await expect(handle.promise).resolves.toEqual({ numPages: 1 });
    expect(GlobalWorkerOptions.workerSrc).toBe("/assets/pdf.worker.js");
    expect(getDocument).toHaveBeenCalledWith({
      url: "/api/share/t/pdf",
      withCredentials: true,
      enableXfa: false,
      // JBIG2 scans need the wasm decoders; without them pages stay blank.
      wasmUrl: "/pdfjs/6.3.289/wasm/",
      iccUrl: "/pdfjs/6.3.289/iccs/",
      cMapUrl: "/pdfjs/6.3.289/cmaps/",
      cMapPacked: true,
      standardFontDataUrl: "/pdfjs/6.3.289/standard_fonts/",
    });
    await handle.destroy();
    expect(destroy).toHaveBeenCalledTimes(1);
  });

  it("never starts a download destroyed before the library loaded", async () => {
    const handle = openPdfDocument("/x.pdf");
    await handle.destroy();
    await expect(handle.promise).rejects.toBeInstanceOf(PdfLoadAborted);
    expect(getDocument).not.toHaveBeenCalled();
    expect(destroy).not.toHaveBeenCalled();
  });
});

describe("loadPdfLibrary", () => {
  it("exposes the library to the viewer module before importing it", async () => {
    const { pdfjs, viewer } = await loadPdfLibrary();
    expect((globalThis as { pdfjsLib?: unknown }).pdfjsLib).toBe(pdfjs);
    expect(viewer.PDFViewer).toBeDefined();
  });
});
