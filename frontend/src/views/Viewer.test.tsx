import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { AssetDoc } from "../api";
import { t } from "../lib/i18n";
import type { EntryFallbackState } from "../lib/useEntryFallback";
import { mockMedia } from "../test-media";
import { Viewer } from "./Viewer";

const getDoc = vi.fn();
const getCollectionFile = vi.fn();
const listVersions = vi.fn();
const getGraph = vi.fn();
const getAssetHtmlGrant = vi.fn();

vi.mock("../api", () => ({
  api: {
    getDoc: (...a: unknown[]) => getDoc(...a),
    getCollectionFile: (...a: unknown[]) => getCollectionFile(...a),
    listVersions: (...a: unknown[]) => listVersions(...a),
    getGraph: (...a: unknown[]) => getGraph(...a),
    getAssetHtmlGrant: (...a: unknown[]) => getAssetHtmlGrant(...a),
    pdfUrl: (slug: string, v?: number) => `/pdf/${slug}${v ? `?version=${v}` : ""}`,
  },
}));

// The data hooks are tested on their own; here they are stubs so each test
// can put the view into the exact state it needs.
interface DocOpts {
  loadDoc: () => Promise<unknown>;
  loadFile: (p: string) => Promise<unknown>;
  hrefFor: (p: string) => string;
  onNavigate: (p: string) => void;
}
const docState = {
  doc: null as AssetDoc | null,
  html: "",
  activePath: "",
  error: null as string | null,
  docErrorStatus: null as number | null,
  collectionCtx: null as { paths: string[]; current: string; hrefFor: (p: string) => string } | null,
};
const openFile = vi.fn();
const reload = vi.fn().mockResolvedValue(undefined);
let lastDocOpts: DocOpts | null = null;
vi.mock("../lib/useCollectionDoc", () => ({
  useCollectionDoc: (opts: DocOpts) => {
    lastDocOpts = opts;
    return { ...docState, openFile, reload };
  },
}));

vi.mock("../lib/useSessionUser", () => ({ useSessionUser: () => null }));

let entryState: EntryFallbackState = "idle";
vi.mock("../lib/useEntryFallback", () => ({ useEntryFallback: () => entryState }));

const preview = { previewVersion: null as number | null };
let lastLoadVersions: (() => Promise<unknown>) | null = null;
vi.mock("../lib/useVersionPreview", () => ({
  useVersionPreview: (o: { loadVersions: () => Promise<unknown> }) => {
    lastLoadVersions = o.loadVersions;
    return {
      previewVersion: preview.previewVersion,
      meta: "v1",
      downloadHref: "/dl",
      staleNotice: null,
      historySection: null,
      historyPanel: <div>history</div>,
      goToVersion: vi.fn(),
    };
  },
}));

// The reader's actions are tested with the hook; here the view only needs
// to know whether the caller manages the asset and which project it is in.
const reader: {
  asset: { id: string } | null;
  project: { name: string; slug: string } | null;
} = { asset: null, project: null };
let lastReaderParams: { downloadHref?: string; relationsHref?: string } | null = null;
vi.mock("../components/reader/useReaderActions", () => ({
  useReaderActions: (p: { downloadHref?: string; relationsHref?: string }) => {
    lastReaderParams = p;
    return {
      asset: reader.asset,
      project: reader.project,
      menu: [],
      share: null,
      dialogs: null,
      onChanged: vi.fn(),
      assignProject: null,
    };
  },
}));
vi.mock("../components/reader/ReaderDetails", () => ({
  ReaderDetails: () => <div>panel</div>,
}));

const vault = {
  newFileOpen: false,
  setNewFileOpen: vi.fn(),
  openFilePicker: vi.fn(),
  onPickedFile: vi.fn().mockResolvedValue(undefined),
  onCreateEmptyFile: vi.fn(),
  onMoveFile: vi.fn(),
  onDeleteFile: vi.fn(),
};
vi.mock("../lib/useVaultFileActions", () => ({
  useVaultFileActions: () => ({ ...vault, fileInputRef: { current: null } }),
}));

vi.mock("../components/shell/PageContext", () => ({
  PageContext: (p: { crumbs?: { label: string }[] }) => (
    <nav data-testid="crumbs">{p.crumbs?.map((b) => b.label).join(" / ") ?? ""}</nav>
  ),
}));
// One stubs module stands in for each of these components.
vi.mock("../components/MarkdownView", () => import("./Viewer.testStubs"));
vi.mock("../components/HtmlBundleView", () => import("./Viewer.testStubs"));
vi.mock("../components/PdfView", () => import("./Viewer.testStubs"));
vi.mock("../components/InlineEditor", () => import("./Viewer.testStubs"));
vi.mock("../components/NewFileDialog", () => import("./Viewer.testStubs"));
vi.mock("../components/VaultGraph", () => import("./Viewer.testStubs"));
vi.mock("../components/reader/CollectionFiles", () => import("./Viewer.testStubs"));

const EDIT = () => t("common.edit");

function makeDoc(over: Partial<AssetDoc> = {}): AssetDoc {
  return {
    id: "a1",
    slug: "doc",
    title: "Handbook",
    kind: "md_single",
    version: 2,
    size_bytes: 10,
    entry_path: "index.md",
    html: "<p>body</p>",
    my_role: "owner_file",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...over,
  };
}

function vaultState(over: Partial<AssetDoc> = {}) {
  docState.doc = makeDoc({ kind: "md_collection", ...over });
  docState.activePath = "notes/a.md";
  docState.html = '<a class="wikilink" href="/v/doc?p=notes%2Fb.md">b</a><a class="wikilink" href="/v/doc">bare</a>';
  docState.collectionCtx = {
    paths: ["index.md", "notes/a.md", "notes/b.md"],
    current: "notes/a.md",
    hrefFor: (p) => p,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  // Desktop: the inspector docks beside the text.
  mockMedia({ width: 1440 });
  window.history.replaceState({}, "", "/v/doc");
  Object.assign(docState, {
    doc: null,
    html: "",
    activePath: "",
    error: null,
    docErrorStatus: null,
    collectionCtx: null,
  });
  entryState = "idle";
  preview.previewVersion = null;
  reader.asset = null;
  reader.project = null;
  lastReaderParams = null;
  localStorage.clear();
  vault.newFileOpen = false;
  lastDocOpts = null;
  lastLoadVersions = null;
});

describe("Viewer states", () => {
  it("shows the loading skeleton until the document arrives", () => {
    const { container } = render(<Viewer slug="doc" />);
    expect(container.querySelector(".skeleton")).not.toBeNull();
    expect(screen.queryByTestId("md")).toBeNull();
  });

  it("keeps the skeleton while the entry resolver decides where to go", () => {
    docState.error = "401";
    entryState = "resolving";
    const { container } = render(<Viewer slug="doc" />);
    expect(container.querySelector(".skeleton")).not.toBeNull();
  });

  it("shows the no-access block when the resolver finds no way in", () => {
    docState.error = "404";
    entryState = "dead-end";
    render(<Viewer slug="doc" />);
    expect(screen.getByRole("heading", { name: "No access" })).toBeInTheDocument();
  });

  it("shows the plain error when the resolver could not help", () => {
    docState.error = "500 Internal Server Error";
    entryState = "unresolved";
    render(<Viewer slug="doc" />);
    expect(screen.getByText("500 Internal Server Error")).toBeInTheDocument();
  });
});

describe("Viewer loaders", () => {
  it("passes slug and version to the doc and file loaders and keeps ver in links", async () => {
    render(<Viewer slug="doc" version={3} />);
    await lastDocOpts!.loadDoc();
    await lastDocOpts!.loadFile("x.md");
    expect(getDoc).toHaveBeenCalledWith("doc", 3);
    expect(getCollectionFile).toHaveBeenCalledWith("doc", "x.md", 3);
    expect(lastDocOpts!.hrefFor("a b.md")).toBe("/v/doc?p=a%20b.md&ver=3");
    lastDocOpts!.onNavigate("x.md");
    expect(window.location.search).toBe("?p=x.md&ver=3");
  });

  it("builds links under a share base path", () => {
    render(<Viewer slug="doc" basePath="/s/tok" />);
    expect(lastDocOpts!.hrefFor("x.md")).toBe("/s/tok?p=x.md");
  });

  it("lists versions only once the asset id is known", async () => {
    listVersions.mockResolvedValue([{ version: 1 }]);
    const { rerender } = render(<Viewer slug="doc" />);
    await expect(lastLoadVersions!()).resolves.toEqual([]);
    expect(listVersions).not.toHaveBeenCalled();
    docState.doc = makeDoc();
    rerender(<Viewer slug="doc" />);
    await expect(lastLoadVersions!()).resolves.toEqual([{ version: 1 }]);
    expect(listVersions).toHaveBeenCalledWith("a1");
  });
});

describe("Viewer single document", () => {
  it("renders markdown with a download link and rewrites the bar to the canonical url", () => {
    window.history.replaceState({}, "", "/v/doc?x=1#part");
    docState.doc = makeDoc({ canonical_url: `${window.location.origin}/v/handbook` });
    docState.html = "<p>body</p>";
    render(<Viewer slug="doc" />);
    expect(screen.getByTestId("md")).toHaveTextContent("body");
    // The download lives in the reader's menu, not on the text.
    expect(screen.getByTestId("md").dataset.download).toBe("");
    expect(lastReaderParams?.downloadHref).toBe("/dl");
    expect(lastReaderParams?.relationsHref).toBe("/v/handbook?tab=relations");
    expect(screen.getByTestId("crumbs")).toHaveTextContent("Documents / Handbook");
    // History sits in the inspector, closed by default for a document.
    expect(screen.queryByText("history")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: t("reader.inspectorShow") }));
    fireEvent.click(screen.getByRole("tab", { name: t("reader.tabHistory") }));
    expect(screen.getByText("history")).toBeInTheDocument();
    expect(window.location.pathname + window.location.search + window.location.hash).toBe(
      "/v/handbook?x=1#part",
    );
  });

  it("does not rewrite the address when mounted under a share path", () => {
    window.history.replaceState({}, "", "/s/tok");
    docState.doc = makeDoc({ canonical_url: "https://ics.example.com/v/handbook" });
    render(<Viewer slug="doc" basePath="/s/tok" />);
    expect(window.location.pathname).toBe("/s/tok");
  });

  it("opens the inline editor for the entry and returns on cancel", () => {
    docState.doc = makeDoc();
    render(<Viewer slug="doc" />);
    fireEvent.click(screen.getByRole("button", { name: EDIT() }));
    expect(screen.getByTestId("editor").dataset.path).toBe("");
    fireEvent.click(screen.getByRole("button", { name: "cancel" }));
    expect(screen.getByTestId("md")).toBeInTheDocument();
  });

  it("reloads the document after the editor saves", async () => {
    docState.doc = makeDoc();
    render(<Viewer slug="doc" />);
    fireEvent.click(screen.getByRole("button", { name: EDIT() }));
    fireEvent.click(screen.getByRole("button", { name: "save" }));
    await waitFor(() => expect(reload).toHaveBeenCalled());
    expect(screen.getByTestId("md")).toBeInTheDocument();
  });

  it("offers no edit action to a read-only viewer", () => {
    docState.doc = makeDoc({ my_role: "viewer" });
    render(<Viewer slug="doc" />);
    expect(screen.queryByRole("button", { name: EDIT() })).toBeNull();
  });

  it("offers no edit action while previewing an archived version", () => {
    docState.doc = makeDoc();
    preview.previewVersion = 1;
    render(<Viewer slug="doc" />);
    expect(screen.queryByRole("button", { name: EDIT() })).toBeNull();
  });

  it("puts the management details in the inspector when the caller manages the asset", () => {
    docState.doc = makeDoc();
    reader.asset = { id: "a1" };
    render(<Viewer slug="doc" />);
    fireEvent.click(screen.getByRole("button", { name: t("reader.inspectorShow") }));
    fireEvent.click(screen.getByRole("tab", { name: t("reader.tabDetails") }));
    expect(screen.getByText("panel")).toBeInTheDocument();
    expect(screen.getByTestId("md")).toBeInTheDocument();
  });

  it("offers no details tab to a reader without management rights", () => {
    docState.doc = makeDoc({ my_role: "viewer" });
    render(<Viewer slug="doc" />);
    fireEvent.click(screen.getByRole("button", { name: t("reader.inspectorShow") }));
    expect(screen.queryByRole("tab", { name: t("reader.tabDetails") })).toBeNull();
    expect(screen.getByRole("tab", { name: t("reader.tabOutline") })).toBeInTheDocument();
  });

  it("puts the project in front of the document in the breadcrumb trail", () => {
    docState.doc = makeDoc();
    reader.asset = { id: "a1" };
    reader.project = { name: "Marketing", slug: "mkt" };
    render(<Viewer slug="doc" />);
    expect(screen.getByTestId("crumbs")).toHaveTextContent("Projects / Marketing / Handbook");
  });

  it("remembers the inspector choice for documents", () => {
    docState.doc = makeDoc();
    render(<Viewer slug="doc" />);
    fireEvent.click(screen.getByRole("button", { name: t("reader.inspectorShow") }));
    expect(JSON.parse(localStorage.getItem("ics-reader-inspector") ?? "{}")).toEqual({ document: true });
    expect(screen.getByRole("button", { name: t("reader.inspectorHide") })).toHaveAttribute("aria-expanded", "true");
  });
});

describe("Viewer html bundle", () => {
  it("renders the bundle view and asks for a grant for the previewed version", async () => {
    docState.doc = makeDoc({ kind: "html_bundle", title: "Dash" });
    preview.previewVersion = 1;
    getAssetHtmlGrant.mockResolvedValue({ url: "https://cdn/x" });
    render(<Viewer slug="doc" />);
    fireEvent.click(screen.getByRole("button", { name: "bundle Dash" }));
    await waitFor(() => expect(document.body.dataset.grant).toBe("https://cdn/x"));
    expect(getAssetHtmlGrant).toHaveBeenCalledWith("doc", 1);
    expect(screen.queryByTestId("md")).toBeNull();
  });

  it("asks for the current version grant when not previewing", async () => {
    docState.doc = makeDoc({ kind: "html_bundle", title: "Dash" });
    getAssetHtmlGrant.mockResolvedValue({ url: "https://cdn/y" });
    render(<Viewer slug="doc" />);
    fireEvent.click(screen.getByRole("button", { name: "bundle Dash" }));
    await waitFor(() => expect(document.body.dataset.grant).toBe("https://cdn/y"));
    expect(getAssetHtmlGrant).toHaveBeenCalledWith("doc", undefined);
  });
});

describe("Viewer pdf", () => {
  it("renders the PDF reader for the current version with a download and no editor", () => {
    docState.doc = makeDoc({ kind: "pdf_doc", title: "Contract" });
    render(<Viewer slug="doc" />);
    const pdf = screen.getByTestId("pdf");
    expect(pdf.dataset.url).toBe("/pdf/doc");
    expect(pdf.dataset.download).toBe("/dl");
    expect(screen.getByTestId("crumbs")).toHaveTextContent("Documents / Contract");
    expect(screen.queryByRole("button", { name: EDIT() })).toBeNull();
    expect(screen.queryByTestId("md")).toBeNull();
  });

  it("reads the archived version in a preview", () => {
    docState.doc = makeDoc({ kind: "pdf_doc", title: "Contract" });
    preview.previewVersion = 2;
    render(<Viewer slug="doc" />);
    expect(screen.getByTestId("pdf").dataset.url).toBe("/pdf/doc?version=2");
  });
});

describe("Viewer collection", () => {
  it("shows breadcrumbs instead of a title and edits the file in view", () => {
    vaultState();
    render(<Viewer slug="doc" />);
    expect(screen.getByTestId("crumbs")).toHaveTextContent("Documents / Handbook / notes / a");
    expect(screen.getByTestId("md").dataset.download).toBe("");
    fireEvent.click(screen.getByRole("button", { name: EDIT() }));
    expect(screen.getByTestId("editor").dataset.path).toBe("notes/a.md");
  });

  it("sets the browser tab title to the document title", () => {
    docState.doc = makeDoc();
    const { rerender } = render(<Viewer slug="doc" />);
    expect(document.title).toBe("Handbook - ICS");
    vaultState();
    rerender(<Viewer slug="doc" />);
    expect(document.title).toBe("a - ICS");
  });

  it("opens files picked in the tree", () => {
    vaultState();
    render(<Viewer slug="doc" />);
    fireEvent.click(screen.getByRole("button", { name: "tree notes/b.md" }));
    expect(openFile).toHaveBeenCalledWith("notes/b.md");
  });

  it("keeps wikilink clicks inside the SPA and ignores links without a path", () => {
    vaultState();
    render(<Viewer slug="doc" />);
    fireEvent.click(screen.getByText("b"));
    expect(openFile).toHaveBeenCalledWith("notes/b.md");
    openFile.mockClear();
    fireEvent.click(screen.getByText("bare"));
    fireEvent.click(screen.getByTestId("md"));
    expect(openFile).not.toHaveBeenCalled();
  });

  it("switches to the graph and back to text when a node is opened", async () => {
    vaultState({ title: null });
    render(<Viewer slug="doc" version={2} />);
    fireEvent.click(screen.getByRole("radio", { name: /Graph/ }));
    expect(await screen.findByTestId("graph")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: EDIT() })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "fetch graph" }));
    expect(getGraph).toHaveBeenCalledWith("doc");
    fireEvent.click(screen.getByRole("button", { name: "open b.md" }));
    expect(openFile).toHaveBeenCalledWith("b.md");
    expect(screen.queryByTestId("graph")).toBeNull();
    expect(screen.getByTestId("md")).toBeInTheDocument();
  });

  it("opens a collection on its file tree", () => {
    vaultState();
    render(<Viewer slug="doc" />);
    expect(screen.getByRole("tab", { name: t("reader.tabFiles") })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("files")).toBeInTheDocument();
  });

  it("keeps the version in breadcrumbs while previewing and hides file actions", () => {
    vaultState();
    preview.previewVersion = 1;
    render(<Viewer slug="doc" />);
    expect(screen.getByTestId("files")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "new file" })).toBeNull();
    expect(screen.queryByRole("button", { name: "upload file" })).toBeNull();
  });

  it("wires the new file and upload actions for an editor", () => {
    vaultState();
    render(<Viewer slug="doc" />);
    fireEvent.click(screen.getByRole("button", { name: "new file" }));
    expect(vault.setNewFileOpen).toHaveBeenCalledWith(true);
    fireEvent.click(screen.getByRole("button", { name: "upload file" }));
    expect(vault.openFilePicker).toHaveBeenCalled();
  });

  it("shows the new file dialog in the current folder and closes it", () => {
    vaultState();
    vault.newFileOpen = true;
    render(<Viewer slug="doc" />);
    const dialog = document.querySelector<HTMLElement>("[data-folder]");
    expect(dialog?.dataset.folder).toBe("notes");
    fireEvent.click(screen.getByRole("button", { name: "close" }));
    expect(vault.setNewFileOpen).toHaveBeenCalledWith(false);
  });
});
