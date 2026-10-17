import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Fake pdf.js viewer components.

type Handler = (e: Record<string, unknown>) => void;

class FakeEventBus {
  handlers = new Map<string, Handler[]>();
  dispatched: Array<[string, Record<string, unknown>]> = [];
  on(name: string, fn: Handler) {
    this.handlers.set(name, [...(this.handlers.get(name) ?? []), fn]);
  }
  dispatch(name: string, data: Record<string, unknown>) {
    this.dispatched.push([name, data]);
    for (const fn of this.handlers.get(name) ?? []) fn(data);
  }
}

class FakeViewer {
  static last: FakeViewer | null = null;
  options: Record<string, unknown>;
  currentScaleValue = "";
  increaseScale = vi.fn();
  decreaseScale = vi.fn();
  updateScale = vi.fn();
  #page = 1;
  constructor(options: Record<string, unknown>) {
    this.options = options;
    FakeViewer.last = this;
  }
  get bus() {
    return this.options.eventBus as FakeEventBus;
  }
  get currentPageNumber() {
    return this.#page;
  }
  set currentPageNumber(n: number) {
    this.#page = n;
    this.bus.dispatch("pagechanging", { pageNumber: n });
  }
  setDocument(doc: unknown) {
    if (doc) this.bus.dispatch("pagesinit", {});
  }
}

const viewerModule = {
  EventBus: FakeEventBus,
  PDFLinkService: class {
    options: unknown;
    constructor(options: unknown) {
      this.options = options;
    }
    setViewer() {}
    setDocument() {}
  },
  PDFFindController: class {},
  PDFViewer: FakeViewer,
  LinkTarget: { BLANK: 2 },
  FindState: { FOUND: 0, NOT_FOUND: 1, WRAPPED: 2, PENDING: 3 },
};
const pdfjs = { AnnotationMode: { ENABLE: 1 }, AnnotationEditorType: { DISABLE: -1 } };

const openPdfDocument = vi.fn();
vi.mock("./pdfjs", () => ({
  openPdfDocument: (url: string) => openPdfDocument(url),
  loadPdfLibrary: () => Promise.resolve({ pdfjs, viewer: viewerModule }),
}));
vi.mock("pdfjs-dist/web/pdf_viewer.css", () => ({}));

const { PdfReader } = await import("./PdfReader");

class FakeResizeObserver {
  observe() {}
  disconnect() {}
}

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", FakeResizeObserver);
  FakeViewer.last = null;
  openPdfDocument.mockReset().mockImplementation(() => ({
    promise: Promise.resolve({ numPages: 3 }),
    destroy: vi.fn(async () => undefined),
  }));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function ready() {
  render(<PdfReader url="/doc.pdf" title="Contract" downloadHref="/dl" />);
  await screen.findByText("of 3");
  const viewer = FakeViewer.last;
  if (!viewer) throw new Error("viewer not created");
  return viewer;
}

describe("PdfReader", () => {
  it("mounts pdf.js' viewer with text, links and no forms, fitted to the box", async () => {
    const viewer = await ready();
    expect(viewer.options).toMatchObject({
      textLayerMode: 1,
      annotationMode: 1,
      annotationEditorMode: -1,
      removePageBorders: true,
    });
    const links = (viewer.options.linkService as { options: Record<string, unknown> }).options;
    expect(links).toMatchObject({ externalLinkTarget: 2, externalLinkRel: "noopener noreferrer nofollow" });
    expect(viewer.currentScaleValue).toBe("auto");
    expect(openPdfDocument).toHaveBeenCalledWith("/doc.pdf");
  });

  it("moves between pages from the buttons and the page field", async () => {
    const viewer = await ready();
    const field = screen.getByLabelText("Page number");
    expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(viewer.currentPageNumber).toBe(2);
    expect(field).toHaveValue("2");
    fireEvent.change(field, { target: { value: "9" } });
    fireEvent.submit(field);
    // Clamped to the last page.
    expect(viewer.currentPageNumber).toBe(3);
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
  });

  it("zooms and fits the width", async () => {
    const viewer = await ready();
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    fireEvent.click(screen.getByRole("button", { name: "Zoom out" }));
    expect(viewer.increaseScale).toHaveBeenCalledOnce();
    expect(viewer.decreaseScale).toHaveBeenCalledOnce();
    act(() => viewer.bus.dispatch("scalechanging", { scale: 1.5 }));
    expect(screen.getByText("150%")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Fit to width" }));
    expect(viewer.currentScaleValue).toBe("page-width");
  });

  it("searches the text layer and steps through matches", async () => {
    const viewer = await ready();
    fireEvent.click(screen.getByRole("button", { name: "Search the document" }));
    const field = screen.getByPlaceholderText("Search the PDF…");
    fireEvent.change(field, { target: { value: "contract" } });
    expect(viewer.bus.dispatched.at(-1)).toEqual([
      "find",
      expect.objectContaining({ query: "contract", type: "", highlightAll: true, findPrevious: false }),
    ]);
    act(() =>
      viewer.bus.dispatch("updatefindmatchescount", { matchesCount: { current: 2, total: 5 } }),
    );
    expect(screen.getByText("2 of 5")).toBeInTheDocument();
    fireEvent.keyDown(field, { key: "Enter", shiftKey: true });
    expect(viewer.bus.dispatched.at(-1)).toEqual([
      "find",
      expect.objectContaining({ type: "again", findPrevious: true }),
    ]);
    act(() => viewer.bus.dispatch("updatefindcontrolstate", { state: 1 }));
    expect(screen.getByText("No matches")).toBeInTheDocument();
    fireEvent.keyDown(field, { key: "Escape" });
    expect(viewer.bus.dispatched.at(-1)?.[0]).toBe("findbarclose");
    expect(screen.queryByPlaceholderText("Search the PDF…")).not.toBeInTheDocument();
  });

  it("opens full screen over the page and closes it with Esc", async () => {
    await ready();
    const reader = screen.getByRole("region", { name: "PDF preview" });
    fireEvent.click(screen.getByRole("button", { name: "Full screen" }));
    expect(reader).toHaveClass("fixed", "inset-0");
    expect(document.body).toHaveClass("overflow-hidden");
    expect(screen.getByText("Contract")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "f", ctrlKey: true });
    expect(screen.getByPlaceholderText("Search the PDF…")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(reader).not.toHaveClass("fixed");
    expect(document.body).not.toHaveClass("overflow-hidden");
  });

  it("zooms with Ctrl + wheel around the pointer", async () => {
    const viewer = await ready();
    const box = document.querySelector(".pdf-reader");
    if (!box) throw new Error("no container");
    fireEvent.wheel(box, { deltaY: -100, ctrlKey: true, clientX: 10, clientY: 20 });
    expect(viewer.updateScale).toHaveBeenCalledWith(
      // A pinch-sized step, capped like the graph views.
      expect.objectContaining({ origin: [10, 20], scaleFactor: 1.6 }),
    );
    fireEvent.wheel(box, { deltaY: -100 });
    expect(viewer.updateScale).toHaveBeenCalledOnce();
  });

  it("explains a document that cannot be opened", async () => {
    openPdfDocument.mockImplementation(() => ({
      promise: Promise.reject(Object.assign(new Error("pw"), { name: "PasswordException" })),
      destroy: vi.fn(async () => undefined),
    }));
    render(<PdfReader url="/locked.pdf" />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/password protected/);
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
  });
});
