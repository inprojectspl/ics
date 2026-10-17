import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { AssetDoc, ShareInfo } from "../api";
import { ApiError } from "../api/_core";
import { t } from "../lib/i18n";
import { ShareView } from "./ShareView";

const getShareInfo = vi.fn();
const getShareDoc = vi.fn();
const getShareCollectionFile = vi.fn();
const getShareHtmlGrant = vi.fn();
const getShareGraph = vi.fn();
const shareMagicClaim = vi.fn();
const shareAuth = vi.fn();

vi.mock("../api", () => ({
  api: {
    getShareInfo: (...a: unknown[]) => getShareInfo(...a),
    getShareDoc: (...a: unknown[]) => getShareDoc(...a),
    getShareCollectionFile: (...a: unknown[]) => getShareCollectionFile(...a),
    getShareVersions: vi.fn().mockResolvedValue([]),
    getShareGraph: (...a: unknown[]) => getShareGraph(...a),
    getShareHtmlGrant: (...a: unknown[]) => getShareHtmlGrant(...a),
    sharePdfUrl: (token: string, v?: number) => `/spdf/${token}${v ? `?version=${v}` : ""}`,
    shareMagicClaim: (...a: unknown[]) => shareMagicClaim(...a),
    shareAuth: (...a: unknown[]) => shareAuth(...a),
  },
}));
// A role holder gets the full owner reader, which has its own tests.
vi.mock("./Viewer", () => ({
  Viewer: (p: { slug: string; basePath: string }) => (
    <div data-testid="owner-viewer" data-slug={p.slug} data-base={p.basePath} />
  ),
}));
// The bundle view mounts a sandboxed iframe; the stub exposes the props the
// share view computes.
vi.mock("../components/HtmlBundleView", () => ({
  HtmlBundleView: (p: {
    accessGated?: boolean;
    downloadHref?: string;
    fetchGrantUrl: () => Promise<string>;
  }) => (
    <div
      data-testid="bundle"
      data-gated={String(!!p.accessGated)}
      data-download={p.downloadHref ?? ""}
    >
      <button
        type="button"
        onClick={async () => document.body.setAttribute("data-grant", await p.fetchGrantUrl())}
      >
        grant
      </button>
    </div>
  ),
}));
// The PDF reader draws canvases through pdf.js; the stub exposes the props
// the view computes.
vi.mock("../components/PdfView", () => ({
  PdfDocument: (p: { url: string; downloadHref?: string; accessGated?: boolean }) => (
    <div
      data-testid="pdf"
      data-url={p.url}
      data-download={p.downloadHref ?? ""}
      data-gated={String(!!p.accessGated)}
    />
  ),
}));
// The graph draws on a canvas jsdom lacks; the stub drives the view's callbacks.
vi.mock("../components/VaultGraph", () => ({
  VaultGraph: (p: { fetcher: () => Promise<unknown>; onOpenFile: (p: string) => void }) => (
    <div data-testid="graph">
      <button type="button" onClick={() => void p.fetcher()}>
        fetch graph
      </button>
      <button type="button" onClick={() => p.onOpenFile("notes/spec.md")}>
        open spec
      </button>
    </div>
  ),
}));

function info(over: Partial<ShareInfo> = {}): ShareInfo {
  return {
    mode: "org_sso",
    requires_password: false,
    requires_login: false,
    requires_magic_link: false,
    has_access: true,
    title: "Knowledge base",
    expires_at: null,
    my_role: null,
    slug: null,
    ...over,
  } as ShareInfo;
}

const collection = {
  id: "a1",
  slug: "vault",
  title: "Knowledge base",
  kind: "md_collection",
  version: 1,
  size_bytes: 10,
  entry_path: "index.md",
  html: "<p>entry</p>",
  tree: ["index.md", "notes/spec.md"],
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
} as AssetDoc;

beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState({}, "", "/s/tok");
  document.body.removeAttribute("data-grant");
  getShareDoc.mockResolvedValue(collection);
  getShareGraph.mockResolvedValue({ nodes: [], edges: [] });
  getShareCollectionFile.mockResolvedValue({
    slug: "vault",
    path: "notes/spec.md",
    html: "<p>spec</p>",
  });
});

describe("ShareView", () => {
  it("opens the file the link points at, instead of the entry page", async () => {
    getShareInfo.mockResolvedValue(info());
    render(<ShareView token="tok" path="notes/spec.md" />);
    await waitFor(() =>
      expect(getShareCollectionFile).toHaveBeenCalledWith("tok", "notes/spec.md", undefined),
    );
  });

  it("tells a visitor the link does not open for them, rather than loading forever", async () => {
    // org_sso opened by a signed-in user outside the allowed domain: there is
    // no access and signing in won't change that, so there is nothing to wait for.
    getShareInfo.mockResolvedValue(info({ has_access: false }));
    render(<ShareView token="tok" />);
    expect(await screen.findByText("No access")).toBeInTheDocument();
    expect(screen.queryByText("Loading…")).toBeNull();
  });

  it("still challenges a password link", async () => {
    getShareInfo.mockResolvedValue(
      info({ mode: "password", requires_password: true, has_access: false }),
    );
    render(<ShareView token="tok" />);
    expect(await screen.findByLabelText(/Password/i)).toBeInTheDocument();
  });
});

describe("ShareView access states", () => {
  it("shows a loading line until the link info arrives", () => {
    getShareInfo.mockReturnValue(new Promise(() => {}));
    render(<ShareView token="tok" />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("explains a dead link", async () => {
    getShareInfo.mockRejectedValue(new Error("link expired"));
    render(<ShareView token="tok" />);
    expect(await screen.findByText("This link does not work")).toBeInTheDocument();
    expect(screen.getByText("link expired")).toBeInTheDocument();
  });

  it("asks for an invite email on a magic-link share", async () => {
    getShareInfo.mockResolvedValue(
      info({ mode: "magic_email", requires_magic_link: true, has_access: false, title: null }),
    );
    render(<ShareView token="tok" />);
    expect(await screen.findByText("Private document")).toBeInTheDocument();
  });

  it("asks an anonymous visitor of an org link to log in", async () => {
    getShareInfo.mockResolvedValue(info({ requires_login: true, has_access: false }));
    render(<ShareView token="tok" />);
    expect(await screen.findByText("Sign-in required")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/#login");
  });

  it("mounts the full reader under the share path for someone with a role", async () => {
    getShareInfo.mockResolvedValue(info({ my_role: "editor", slug: "vault" }));
    render(<ShareView token="tok" />);
    const viewer = await screen.findByTestId("owner-viewer");
    expect(viewer.dataset.slug).toBe("vault");
    expect(viewer.dataset.base).toBe("/s/tok");
  });
});

describe("ShareView magic link claim", () => {
  it("claims the token, strips it from the url and keeps other params", async () => {
    window.history.replaceState({}, "", "/s/tok?m=abc&ver=2");
    shareMagicClaim.mockResolvedValue({ ok: true, email: "a@example.com" });
    getShareInfo.mockResolvedValue(info({ has_access: false }));
    render(<ShareView token="tok" />);
    expect(await screen.findByText("No access")).toBeInTheDocument();
    expect(shareMagicClaim).toHaveBeenCalledWith("tok", "abc");
    expect(window.location.pathname + window.location.search).toBe("/s/tok?ver=2");
  });

  it("shows the claim error on the magic-link screen", async () => {
    window.history.replaceState({}, "", "/s/tok?m=bad");
    shareMagicClaim.mockRejectedValue(new Error("token already used"));
    getShareInfo.mockResolvedValue(
      info({ mode: "magic_email", requires_magic_link: true, has_access: false }),
    );
    render(<ShareView token="tok" />);
    expect(await screen.findByText("token already used")).toBeInTheDocument();
    expect(window.location.search).toBe("");
  });
});

describe("ShareView password gate", () => {
  function gated() {
    getShareInfo.mockResolvedValueOnce(
      info({ mode: "password", requires_password: true, has_access: false, title: null }),
    );
  }

  it("rejects a wrong password", async () => {
    gated();
    shareAuth.mockRejectedValue(new Error("401"));
    render(<ShareView token="tok" />);
    fireEvent.change(await screen.findByLabelText(/Password/i), { target: { value: "wrong" } });
    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    expect(await screen.findByText("Wrong password")).toBeInTheDocument();
    expect(shareAuth).toHaveBeenCalledWith("tok", "wrong");
  });

  it("reloads the link info and opens the document after the right password", async () => {
    gated();
    getShareInfo.mockResolvedValue(info());
    shareAuth.mockResolvedValue({ ok: true });
    render(<ShareView token="tok" />);
    fireEvent.change(await screen.findByLabelText(/Password/i), { target: { value: "ok" } });
    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    expect(await screen.findByText("entry")).toBeInTheDocument();
    expect(getShareInfo).toHaveBeenCalledTimes(2);
  });
});

describe("ShareView content", () => {
  const single = {
    ...collection,
    kind: "md_single",
    title: "Note",
    tree: null,
    entry_path: null,
    html: "<p>content</p>",
  } as AssetDoc;

  it("shows the document error inside the share", async () => {
    getShareInfo.mockResolvedValue(info());
    getShareDoc.mockRejectedValue(new Error("document deleted"));
    render(<ShareView token="tok" />);
    expect(await screen.findByText("document deleted")).toBeInTheDocument();
  });

  it("renders a single markdown document for the requested version", async () => {
    getShareInfo.mockResolvedValue(info());
    getShareDoc.mockResolvedValue(single);
    render(<ShareView token="tok" version={1} />);
    expect(await screen.findByText("content")).toBeInTheDocument();
    expect(getShareDoc).toHaveBeenCalledWith("tok", 1);
  });

  it("offers the download of the current version in the reader menu", async () => {
    getShareInfo.mockResolvedValue(info());
    getShareDoc.mockResolvedValue(single);
    const assign = vi.fn();
    vi.spyOn(window, "location", "get").mockReturnValue({ ...window.location, assign } as Location);
    render(<ShareView token="tok" />);
    await screen.findByText("content");
    fireEvent.click(screen.getByRole("button", { name: t("documentRow.actions", { title: "Note" }) }));
    fireEvent.click(await screen.findByRole("menuitem", { name: t("reader.download") }));
    expect(assign).toHaveBeenCalledWith("/api/share/tok/download");
  });

  it("sets the browser tab title to the article title", async () => {
    getShareInfo.mockResolvedValue(info());
    getShareDoc.mockResolvedValue(single);
    const { unmount } = render(<ShareView token="tok" />);
    await screen.findByText("content");
    expect(document.title).toBe("Note - ICS");
    unmount();
    expect(document.title).not.toContain("Note");
  });

  it("gates a critical html bundle and hides its download", async () => {
    getShareInfo.mockResolvedValue(info());
    getShareDoc.mockResolvedValue({
      ...single,
      kind: "html_bundle",
      security_status: "critical",
      security_bypass: false,
    });
    render(<ShareView token="tok" />);
    const bundle = await screen.findByTestId("bundle");
    expect(bundle.dataset.gated).toBe("true");
    expect(bundle.dataset.download).toBe("");
  });

  it("renders a PDF through the share endpoint", async () => {
    getShareInfo.mockResolvedValue(info());
    getShareDoc.mockResolvedValue({ ...single, kind: "pdf_doc", security_status: "clean" });
    render(<ShareView token="tok" />);
    const pdf = await screen.findByTestId("pdf");
    expect(pdf.dataset.url).toBe("/spdf/tok");
    expect(pdf.dataset.gated).toBe("false");
    expect(pdf.dataset.download).not.toBe("");
  });

  it("gates a critical PDF", async () => {
    getShareInfo.mockResolvedValue(info());
    getShareDoc.mockResolvedValue({
      ...single,
      kind: "pdf_doc",
      security_status: "critical",
      security_bypass: false,
    });
    render(<ShareView token="tok" />);
    expect((await screen.findByTestId("pdf")).dataset.gated).toBe("true");
  });

  it("renders a converted office document read-only with the original download", async () => {
    getShareInfo.mockResolvedValue(info());
    getShareDoc.mockResolvedValue({
      ...single,
      kind: "office_doc",
      html: "<p>about wombats</p>",
      security_status: "clean",
      document: { source_format: "odt", images: 0 },
    });
    render(<ShareView token="tok" />);
    expect(await screen.findByText("about wombats")).toBeInTheDocument();
    expect(screen.getByText(/from a \.odt file/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download original" })).toBeInTheDocument();
  });

  it("gates a critical office document the visitor still received", async () => {
    getShareInfo.mockResolvedValue(info());
    getShareDoc.mockResolvedValue({
      ...single,
      kind: "office_doc",
      html: "<p>about wombats</p>",
      security_status: "critical",
      security_bypass: false,
    });
    render(<ShareView token="tok" />);
    expect(await screen.findByText("On hold")).toBeInTheDocument();
    expect(screen.queryByText("about wombats")).toBeNull();
  });

  it("shows the review notice when the backend withholds the document", async () => {
    getShareInfo.mockResolvedValue(info());
    getShareDoc.mockRejectedValue(new ApiError(410, "withheld", "410", "bundle_withheld"));
    render(<ShareView token="tok" />);
    expect(await screen.findByText("On hold")).toBeInTheDocument();
  });

  it("serves a clean html bundle through a share grant", async () => {
    getShareInfo.mockResolvedValue(info());
    getShareDoc.mockResolvedValue({ ...single, kind: "html_bundle", security_status: "clean" });
    getShareHtmlGrant.mockResolvedValue({ url: "https://cdn/g" });
    render(<ShareView token="tok" />);
    const bundle = await screen.findByTestId("bundle");
    expect(bundle.dataset.gated).toBe("false");
    expect(bundle.dataset.download).not.toBe("");
    fireEvent.click(screen.getByRole("button", { name: "grant" }));
    await waitFor(() => expect(document.body.dataset.grant).toBe("https://cdn/g"));
    expect(getShareHtmlGrant).toHaveBeenCalledWith("tok", undefined);
  });

  it("switches a collection to the graph and back when a node is opened", async () => {
    getShareInfo.mockResolvedValue(info());
    render(<ShareView token="tok" />);
    fireEvent.click(await screen.findByRole("radio", { name: /Graph/ }));
    expect(await screen.findByTestId("graph")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "fetch graph" }));
    expect(getShareGraph).toHaveBeenCalledWith("tok");
    fireEvent.click(screen.getByRole("button", { name: "open spec" }));
    expect(await screen.findByText("spec", { selector: "p" })).toBeInTheDocument();
    expect(getShareCollectionFile).toHaveBeenCalledWith("tok", "notes/spec.md", undefined);
    expect(screen.queryByTestId("graph")).toBeNull();
  });

  it("follows hash wikilinks inside the token and ignores other links", async () => {
    getShareInfo.mockResolvedValue(info());
    getShareDoc.mockResolvedValue({
      ...collection,
      html: '<p><a class="wikilink" href="#p=notes%2Fspec.md">to the spec</a> <a class="wikilink" href="/v/x">external</a></p>',
    });
    render(<ShareView token="tok" />);
    fireEvent.click(await screen.findByText("external"));
    expect(getShareCollectionFile).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("to the spec"));
    expect(await screen.findByText("spec", { selector: "p" })).toBeInTheDocument();
    expect(getShareCollectionFile).toHaveBeenCalledWith("tok", "notes/spec.md", undefined);
  });
});
