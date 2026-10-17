import { useState, type ReactElement } from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { act, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { AssetSummary, ProjectSummary } from "../../api";
import { api } from "../../api";
import { t } from "../../lib/i18n";
import { renderWithClient } from "../../test-utils";
import { mockMedia } from "../../test-media";
import { useMediaQuery } from "../../lib/useMediaQuery";
import { ConfirmProvider } from "../ConfirmDialog";
import { ShellContext, type ShellApi } from "../shell/shellContext";
import { ToastProvider } from "../Toast";
import { CollectionFiles } from "./CollectionFiles";
import { DocumentOutline } from "./DocumentOutline";
import { readOutline } from "./outline";
import { ReaderDetails } from "./ReaderDetails";
import { ReaderLayout, type InspectorState, type InspectorTab } from "./ReaderLayout";
import { ReaderToolbar } from "./ReaderToolbar";
import { RenameDialog } from "./RenameDialog";
import { INSPECTOR_DOCKED, useInspector } from "./useInspector";
import { useReaderActions } from "./useReaderActions";

function mk(over: Partial<AssetSummary> = {}): AssetSummary {
  return {
    id: "a1",
    slug: "s1",
    title: "Plan",
    kind: "md_single",
    size_bytes: 1024,
    version: 2,
    security_status: "clean",
    created_at: "2026-09-01T10:00:00Z",
    updated_at: "2026-09-29T10:00:00Z",
    ...over,
  };
}

beforeEach(() => {
  localStorage.clear();
  Element.prototype.scrollIntoView = vi.fn();
});

describe("readOutline", () => {
  it("takes h2 and h3 with ids, without the anchor glyph", () => {
    const root = document.createElement("div");
    root.innerHTML =
      '<h1 id="t">Title</h1><h2 id="a">Introduction<a class="heading-anchor">#</a></h2><h3 id="b">Details</h3><h2>No id</h2><h3 id="c"> </h3>';
    expect(readOutline(root)).toEqual([
      { id: "a", text: "Introduction", level: 2 },
      { id: "b", text: "Details", level: 3 },
    ]);
  });
});

describe("DocumentOutline", () => {
  it("jumps to a section, moves focus there and marks it", () => {
    document.body.insertAdjacentHTML("beforeend", '<h2 id="sec-a">A</h2><h3 id="sec-b">B</h3>');
    const onJump = vi.fn();
    render(
      <DocumentOutline
        entries={[
          { id: "sec-a", text: "A", level: 2 },
          { id: "sec-b", text: "B", level: 3 },
        ]}
        onJump={onJump}
      />,
    );
    const link = screen.getByRole("link", { name: "B" });
    fireEvent.click(link);
    expect(document.getElementById("sec-b")).toHaveFocus();
    expect(link).toHaveAttribute("aria-current", "location");
    expect(window.location.hash).toBe("#sec-b");
    expect(onJump).toHaveBeenCalled();
    document.getElementById("sec-a")?.remove();
    document.getElementById("sec-b")?.remove();
  });

  it("says when the document has no headings", () => {
    render(<DocumentOutline entries={[]} />);
    expect(screen.getByText(t("reader.outlineEmpty"))).toBeInTheDocument();
  });
});

function shell(over: Partial<ShellApi> = {}): ShellApi {
  return { contextSlot: null, focusMode: false, setFocusMode: vi.fn(), setActiveHref: vi.fn(), signedIn: true, ...over };
}

function Layout({ panels, initial = true }: { panels: Partial<Record<InspectorTab, ReactElement>>; initial?: boolean }) {
  const [open, setOpen] = useState(initial);
  const [tab, setTab] = useState<InspectorTab>("outline");
  const inspector: InspectorState = { open, tab, setOpen, setTab, docked: useMediaQuery(INSPECTOR_DOCKED) };
  return (
    <ReaderLayout toolbar={<div>toolbar</div>} inspector={inspector} panels={panels} banner={<div>banner</div>}>
      <p>text</p>
    </ReaderLayout>
  );
}

describe("ReaderLayout", () => {
  it("docks the inspector beside the text on wide screens, tabs move with arrows", () => {
    mockMedia({ width: 1440 });
    render(<Layout panels={{ files: <p>files</p>, outline: <p>outline</p>, history: <p>history</p> }} />);
    const aside = screen.getByRole("complementary", { name: t("reader.inspector") });
    const tabs = within(aside).getAllByRole("tab");
    expect(tabs.map((x) => x.textContent)).toEqual([t("reader.tabFiles"), t("reader.tabOutline"), t("reader.tabHistory")]);
    expect(within(aside).getByRole("tab", { name: t("reader.tabOutline") })).toHaveAttribute("aria-selected", "true");
    expect(within(aside).getByRole("tabpanel")).toHaveTextContent("outline");
    fireEvent.keyDown(within(aside).getByRole("tablist"), { key: "ArrowRight" });
    expect(within(aside).getByRole("tabpanel")).toHaveTextContent("history");
    fireEvent.keyDown(within(aside).getByRole("tablist"), { key: "ArrowRight" });
    expect(within(aside).getByRole("tabpanel")).toHaveTextContent("files");
    fireEvent.keyDown(within(aside).getByRole("tablist"), { key: "ArrowLeft" });
    expect(within(aside).getByRole("tabpanel")).toHaveTextContent("history");
    fireEvent.click(within(aside).getByRole("tab", { name: t("reader.tabFiles") }));
    expect(within(aside).getByRole("tabpanel")).toHaveTextContent("files");
  });

  it("falls back to the first tab it has and hides in focus mode", () => {
    mockMedia({ width: 1440 });
    render(
      <ShellContext.Provider value={shell({ focusMode: true })}>
        <Layout panels={{ details: <p>details</p> }} />
      </ShellContext.Provider>,
    );
    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
  });

  it("is a drawer below 1280 px that closes from Escape", async () => {
    mockMedia({ width: 1100 });
    render(<Layout panels={{ details: <p>details</p> }} />);
    expect(screen.getByRole("dialog", { name: t("reader.inspector") })).toHaveTextContent("details");
    // A single tab needs no tab list.
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});

describe("ReaderToolbar", () => {
  it("offers edit and share, toggles reading focus and the inspector", () => {
    const api = shell();
    const onEdit = vi.fn();
    const onShare = vi.fn();
    const toggle = vi.fn();
    render(
      <ShellContext.Provider value={api}>
        <ReaderToolbar
          start={<span>v2</span>}
          onEdit={onEdit}
          onShare={onShare}
          menu={[{ key: "x", label: "Pobierz", onClick: vi.fn() }]}
          menuLabel="Actions"
          inspector={{ open: false, toggle, label: t("reader.inspectorShow") }}
        />
      </ShellContext.Provider>,
    );
    expect(screen.getByRole("toolbar", { name: t("reader.toolbar") })).toHaveTextContent("v2");
    fireEvent.click(screen.getByRole("button", { name: t("common.edit") }));
    fireEvent.click(screen.getByRole("button", { name: t("common.share") }));
    expect(onEdit).toHaveBeenCalled();
    expect(onShare).toHaveBeenCalled();
    const focus = screen.getByRole("button", { name: t("reader.focusOn") });
    expect(focus).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(focus);
    expect(api.setFocusMode).toHaveBeenCalledWith(true);
    const panel = screen.getByRole("button", { name: t("reader.inspectorShow") });
    expect(panel).toHaveAttribute("aria-expanded", "false");
    expect(panel).toHaveAttribute("aria-controls", "reader-inspector");
    fireEvent.click(panel);
    expect(toggle).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Actions" })).toBeInTheDocument();
  });

  it("link visitors get no focus toggle; an empty menu shows no button", () => {
    render(
      <ShellContext.Provider value={shell({ signedIn: false, focusMode: true })}>
        <ReaderToolbar menu={[]} menuLabel="Actions" />
      </ShellContext.Provider>,
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("useInspector", () => {
  it("opens a collection on its files, keeps a document closed and remembers the choice", () => {
    mockMedia({ width: 1440 });
    const col = renderHook(() => useInspector("collection")).result;
    expect(col.current.open).toBe(true);
    expect(col.current.tab).toBe("files");
    const doc = renderHook(() => useInspector("document")).result;
    expect(doc.current.open).toBe(false);
    expect(doc.current.tab).toBe("outline");
    act(() => doc.current.setOpen(true));
    act(() => doc.current.setTab("details"));
    expect(doc.current.tab).toBe("details");
    expect(renderHook(() => useInspector("document")).result.current.open).toBe(true);
  });

  it("on a phone opens only when asked and does not overwrite the docked choice", () => {
    mockMedia({ width: 390 });
    localStorage.setItem("ics-reader-inspector", JSON.stringify({ document: true }));
    const col = renderHook(() => useInspector("collection")).result;
    expect(col.current.open).toBe(false);
    expect(renderHook(() => useInspector("document")).result.current.open).toBe(false);
    act(() => col.current.setOpen(true));
    expect(col.current.open).toBe(true);
    act(() => col.current.setOpen(false));
    expect(JSON.parse(localStorage.getItem("ics-reader-inspector") ?? "{}")).toEqual({ document: true });
  });

  it("stays closed while the kind is unknown and remembers nothing then", () => {
    const r = renderHook(() => useInspector(null)).result;
    expect(r.current.open).toBe(false);
    act(() => r.current.setOpen(true));
    expect(r.current.open).toBe(true);
    expect(localStorage.getItem("ics-reader-inspector")).toBeNull();
  });
});

function withProviders(client: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>
      <ToastProvider>
        <ConfirmProvider>{children}</ConfirmProvider>
      </ToastProvider>
    </QueryClientProvider>
  );
}

const project: ProjectSummary = {
  id: "p1",
  slug: "alpha",
  name: "Alpha",
  description: null,
  created_by: null,
  created_at: "2026-09-01T00:00:00Z",
  my_role: "owner",
  member_count: 1,
  asset_count: 1,
};

describe("useReaderActions", () => {
  it("a reader gets download and relations only, without asking for the summary", () => {
    const summary = vi.spyOn(api, "getAssetSummary");
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(
      () => useReaderActions({ slug: "s1", role: "viewer", previewVersion: null, reload: vi.fn(), downloadHref: "/dl", relationsHref: "/v/s1?tab=relations" }),
      { wrapper: withProviders(client) },
    );
    expect(result.current.asset).toBeNull();
    expect(result.current.share).toBeNull();
    expect(result.current.menu.map((m) => m.key)).toEqual(["download", "relations"]);
    expect(summary).not.toHaveBeenCalled();
  });

  it("an owner gets pin, the managed actions and a share button; the project is resolved", async () => {
    vi.spyOn(api, "getAssetSummary").mockResolvedValue(mk({ project_id: "p1" }));
    vi.spyOn(api, "listProjects").mockResolvedValue({ items: [project], total: 1, page: 1, page_size: 200 } as Awaited<
      ReturnType<typeof api.listProjects>
    >);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useReaderActions({ slug: "s1", role: "owner_file", previewVersion: null, reload: vi.fn() }), {
      wrapper: withProviders(client),
    });
    await waitFor(() => expect(result.current.asset).not.toBeNull());
    await waitFor(() => expect(result.current.project?.name).toBe("Alpha"));
    const keys = result.current.menu.map((m) => m.key);
    expect(keys[0]).toBe("pin");
    expect(keys).toContain("delete");
    expect(keys).not.toContain("share");
    expect(result.current.menu.find((m) => m.key === "rename")?.heading).toBe(t("reader.manage"));
    expect(result.current.share).toBeInstanceOf(Function);
    expect(result.current.assignProject).toBeInstanceOf(Function);
  });

  it("a blocked share stays in the menu with its reason, with no share button", async () => {
    vi.spyOn(api, "getAssetSummary").mockResolvedValue(mk({ security_status: "critical" }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useReaderActions({ slug: "s1", role: "owner_file", previewVersion: null, reload: vi.fn() }), {
      wrapper: withProviders(client),
    });
    await waitFor(() => expect(result.current.asset).not.toBeNull());
    expect(result.current.share).toBeNull();
    expect(result.current.menu.find((m) => m.key === "share")?.disabled).toBe(true);
  });

  it("rename opens a dialog that commits the new title", async () => {
    vi.spyOn(api, "getAssetSummary").mockResolvedValue(mk());
    const rename = vi.spyOn(api, "renameAsset").mockResolvedValue({ id: "a1", title: "New" });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    function Harness() {
      const r = useReaderActions({ slug: "s1", role: "editor", previewVersion: null, reload: vi.fn() });
      return (
        <>
          {r.menu.map((m) => (
            <button key={m.key} type="button" onClick={m.onClick}>
              {m.label}
            </button>
          ))}
          {r.dialogs}
        </>
      );
    }
    const Wrap = withProviders(client);
    render(
      <Wrap>
        <Harness />
      </Wrap>,
    );
    fireEvent.click(await screen.findByRole("button", { name: t("assetMenu.rename") }));
    const input = screen.getByRole("textbox", { name: t("assetToolbar.nameLabel") });
    fireEvent.change(input, { target: { value: "New" } });
    fireEvent.click(screen.getByRole("button", { name: t("common.save") }));
    await waitFor(() => expect(rename).toHaveBeenCalledWith("a1", "New"));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});

describe("RenameDialog", () => {
  it("closes without a call when nothing changed", () => {
    const onRename = vi.fn();
    const onClose = vi.fn();
    render(<RenameDialog title="Plan" onRename={onRename} onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: t("common.save") }));
    expect(onRename).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });
});

describe("CollectionFiles", () => {
  it("shows the tree with its size and the editor actions", () => {
    const onSelect = vi.fn();
    const onCreate = vi.fn();
    const onUpload = vi.fn();
    render(
      <CollectionFiles
        tree={["a.md", "dir/b.md"]}
        currentPath="a.md"
        onSelect={onSelect}
        onCreateFile={onCreate}
        onUploadFile={onUpload}
        downloadHref="/zip"
      />,
    );
    expect(screen.getByText("2")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: t("collectionLayout.newFile") }));
    fireEvent.click(screen.getByRole("button", { name: t("collectionLayout.upload") }));
    expect(onCreate).toHaveBeenCalled();
    expect(onUpload).toHaveBeenCalled();
    expect(screen.getByRole("link", { name: t("collectionLayout.zip") })).toHaveAttribute("href", "/zip");
  });

  it("a reader without a download sees only the tree", () => {
    render(<CollectionFiles tree={["a.md"]} currentPath="a.md" onSelect={vi.fn()} />);
    expect(screen.queryByRole("heading", { name: t("collectionLayout.actions") })).not.toBeInTheDocument();
  });
});

describe("ReaderDetails", () => {
  it("lists what the document is, where it lives and the facts", async () => {
    vi.spyOn(api, "getAssetMeta").mockResolvedValue({
      summary: "Description",
      summary_source: "human",
      summary_version: 2,
      doc_type: null,
      freshness: "current",
      flags: [],
      content_updated_at: null,
      maintainer: null,
      review_due_at: null,
      reviewed_at: null,
      language: null,
      properties: {},
      tags: [],
      slug: "s1",
    } as unknown as Awaited<ReturnType<typeof api.getAssetMeta>>);
    vi.spyOn(api, "listRelations").mockResolvedValue({ outgoing: [], incoming: [] } as unknown as Awaited<ReturnType<typeof api.listRelations>>);
    vi.spyOn(api, "listProjectShares").mockResolvedValue([
      { project_id: "p2", project_slug: "beta", project_name: "Beta", role: "viewer", created_at: null },
    ]);
    const assign = vi.fn();
    renderWithClient(
      <ToastProvider>
        <ReaderDetails
          asset={mk({ project_id: "p1", owner: { id: "u", email: "o@x", display_name: "Olivia" }, active_share_modes: ["public"] })}
          project={project}
          onChanged={vi.fn()}
          onAssignProject={assign}
        />
      </ToastProvider>,
    );
    expect(screen.getByRole("link", { name: "Alpha" })).toHaveAttribute("href", "/projects/alpha");
    expect(await screen.findByRole("link", { name: "Beta" })).toHaveAttribute("href", "/projects/beta");
    expect(screen.getByText("Olivia")).toBeInTheDocument();
    expect(screen.getByText("v2")).toBeInTheDocument();
    expect(screen.getByText(t("shareStatus.public"))).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: t("assetToolbar.changeProject") }));
    expect(assign).toHaveBeenCalled();
  });

  it("names a project the reader cannot see", () => {
    vi.spyOn(api, "getAssetMeta").mockReturnValue(new Promise(() => {}));
    vi.spyOn(api, "listRelations").mockReturnValue(new Promise(() => {}));
    renderWithClient(
      <ToastProvider>
        <ReaderDetails asset={mk({ project_id: "p9", my_role: "viewer" })} project={null} onChanged={vi.fn()} onAssignProject={null} />
      </ToastProvider>,
    );
    expect(screen.getByText(t("assetToolbar.hiddenProject"))).toBeInTheDocument();
  });

  it("does not offer moving the file to an editor, whom the backend refuses", () => {
    vi.spyOn(api, "getAssetMeta").mockReturnValue(new Promise(() => {}));
    vi.spyOn(api, "listRelations").mockReturnValue(new Promise(() => {}));
    renderWithClient(
      <ToastProvider>
        <ReaderDetails asset={mk({ project_id: "p1", my_role: "editor" })} project={project} onChanged={vi.fn()} onAssignProject={vi.fn()} />
      </ToastProvider>,
    );
    expect(screen.queryByRole("button", { name: t("assetToolbar.changeProject") })).not.toBeInTheDocument();
  });
});
