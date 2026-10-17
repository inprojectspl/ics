import { Suspense, useMemo, useState, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { Neighbourhood, NeighbourhoodNode, ProjectGraph, RelationEdge } from "../../api";
import { RELATION_TYPES } from "../../api/relationTypes";
import type { CardScene } from "../../components/graph";
import { ShellContext, type ShellApi } from "../../components/shell/shellContext";
import { t, tn } from "../../lib/i18n";
import * as nav from "../../lib/navigate";
import { renderWithClient } from "../../test-utils";
import { GraphExplorer } from "./GraphExplorer";
import { GraphExplorerLazy } from "./lazy";
import { windowOf } from "./LoadedList";

const getNeighbourhood = vi.fn();
const getProjectGraph = vi.fn();
const listProjects = vi.fn();
const searchAssets = vi.fn();
const findGraphPath = vi.fn();

vi.mock("../../api", () => ({
  api: {
    getNeighbourhood: (...a: unknown[]) => getNeighbourhood(...a),
    getProjectGraph: (...a: unknown[]) => getProjectGraph(...a),
    listProjects: (...a: unknown[]) => listProjects(...a),
    searchAssets: (...a: unknown[]) => searchAssets(...a),
    findGraphPath: (...a: unknown[]) => findGraphPath(...a),
  },
}));
vi.mock("../../lib/useDocTypes", () => ({
  useDocTypeLabels: () => new Map(),
  useDocTypeLabel: () => (key: string | null) => key ?? "",
  useDocTypes: () => [],
}));
// jsdom has no canvas: every card becomes a button that clicks like the canvas does.
vi.mock("../../components/graph", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../components/graph")>()),
  CardCanvas: ({ scene, label, onSelect }: { scene: CardScene; label: string; onSelect: (id: string | null) => void }) => (
    <div role="img" aria-label={label}>
      {scene.cards.map((c) => (
        <button key={c.id} type="button" data-card={c.id} onClick={() => onSelect(c.id)}>
          {c.title}
        </button>
      ))}
    </div>
  ),
}));

function nnode(id: string, depth: number, over: Partial<NeighbourhoodNode> = {}): NeighbourhoodNode {
  return {
    id,
    slug: `s${id}`,
    title: `Doc ${id}`,
    kind: "md_single",
    doc_type: null,
    freshness: "current",
    summary: null,
    estimated_tokens: null,
    depth,
    expandable: true,
    ...over,
  } as NeighbourhoodNode;
}

const edge = (id: string, source: string, target: string): RelationEdge => ({
  id,
  relation_type: "derived_from",
  source_id: source,
  target_id: target,
  source_path: null,
  target_path: null,
  target_anchor: null,
  target_version: null,
  target_version_now: null,
  target_changed: false,
  note: null,
  origin: "manual",
  created_at: null,
});

const hoods: Record<string, Neighbourhood> = {
  sa: {
    root_id: "a",
    depth: 1,
    types: [...RELATION_TYPES],
    nodes: [nnode("a", 0), nnode("b", 1), nnode("c", 1, { expandable: false })],
    edges: [edge("ba", "b", "a"), edge("ac", "a", "c")],
    truncated: false,
    max_nodes: 100,
  },
  sb: {
    root_id: "b",
    depth: 1,
    types: [...RELATION_TYPES],
    nodes: [nnode("b", 0), nnode("a", 1), nnode("d", 1)],
    edges: [edge("ba", "b", "a"), edge("db", "d", "b")],
    truncated: false,
    max_nodes: 100,
  },
};

const projectGraph: ProjectGraph = {
  project: { id: "p", slug: "p1", name: "Apollo" },
  nodes: [
    { ...nnode("a", 0), superseded_by: null, content_updated_at: null, external: false },
    { ...nnode("x", 0), superseded_by: null, content_updated_at: null, external: true },
  ],
  edges: [],
  truncated: false,
  max_nodes: 1000,
};

beforeEach(() => {
  searchAssets.mockReset().mockResolvedValue([]);
  findGraphPath.mockReset();
  getNeighbourhood.mockReset().mockImplementation((slug: string) => Promise.resolve(hoods[slug]));
  getProjectGraph.mockReset().mockResolvedValue(projectGraph);
  listProjects.mockReset().mockResolvedValue({
    items: [{ id: "p", slug: "p1", name: "Apollo", description: null, created_by: null, created_at: "", my_role: "owner", member_count: 1, asset_count: 1 }],
    total: 1,
    page: 1,
    page_size: 200,
  });
});

const canvas = () => screen.getByRole("img");
const rowsOf = (region: HTMLElement) =>
  within(within(region).getByRole("list")).getAllByRole("button").map((b) => b.textContent);

/** The shell's focus switch, as the app frame provides it. */
function Shell({ children }: { children: ReactNode }) {
  const [focusMode, setFocusMode] = useState(false);
  const api = useMemo<ShellApi>(
    () => ({ contextSlot: null, focusMode, setFocusMode, setActiveHref: () => {}, signedIn: true }),
    [focusMode],
  );
  return <ShellContext.Provider value={api}>{children}</ShellContext.Provider>;
}

describe("GraphExplorer", () => {
  it("gives the graph the page in focus mode", async () => {
    renderWithClient(
      <Shell>
        <GraphExplorer />
      </Shell>,
    );
    await screen.findByRole("img");
    expect(screen.getByRole("heading", { level: 1, name: t("graphExplorer.title") })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: t("graphExplorer.focusOn") }));
    expect(screen.queryByRole("heading", { level: 1 })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: t("graphExplorer.focusOff") }));
    expect(screen.getByRole("heading", { level: 1, name: t("graphExplorer.title") })).toBeInTheDocument();
  });

  it("floats the panel over the canvas and minimises it to a pill naming the selection, remembered", async () => {
    localStorage.removeItem("ics-explorer-panel");
    const { unmount } = renderWithClient(<GraphExplorer />);
    const project = await within(await screen.findByRole("img")).findByRole("button", { name: "Apollo" });
    expect(screen.getByRole("region", { name: t("graphExplorer.panelButton") })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: t("graphExplorer.panelMinimize") }));
    expect(screen.queryByRole("region", { name: t("graphExplorer.panelButton") })).toBeNull();
    expect(localStorage.getItem("ics-explorer-panel")).toBe("minimized");
    fireEvent.click(project);
    const pill = screen.getByRole("button", { name: "Apollo", expanded: false });
    unmount();

    renderWithClient(<GraphExplorer />);
    await screen.findByRole("img");
    expect(screen.queryByRole("region", { name: t("graphExplorer.panelButton") })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: t("graphExplorer.panelButton"), expanded: false }));
    expect(screen.getByRole("region", { name: t("graphExplorer.panelButton") })).toBeInTheDocument();
    expect(pill).not.toBeInTheDocument();
  });

  it("loads lazily", async () => {
    renderWithClient(
      <Suspense fallback={<p>lazy-fallback</p>}>
        <GraphExplorerLazy />
      </Suspense>,
    );
    expect(screen.getByText("lazy-fallback")).toBeInTheDocument();
    expect(await screen.findByRole("img")).toBeInTheDocument();
  });

  it("starts from the projects and expands one on click", async () => {
    renderWithClient(<GraphExplorer />);
    const project = await within(await screen.findByRole("img")).findByRole("button", { name: "Apollo" });
    // No count until a document is on the canvas.
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    fireEvent.click(project);
    expect(await within(canvas()).findByRole("button", { name: "Doc a" })).toBeInTheDocument();
    expect(getProjectGraph).toHaveBeenCalledWith("p1", { tasks: true });
    // Documents outside the project are not its children.
    expect(within(canvas()).queryByRole("button", { name: "Doc x" })).toBeNull();
    expect(screen.getByText(tn("graphExplorer.loadedCount", 1))).toBeInTheDocument();
  });

  it("opens a document one level deep and walks on from a clicked card", async () => {
    renderWithClient(<GraphExplorer doc="sa" />);
    expect(await screen.findByRole("heading", { level: 1, name: "Doc a" })).toBeInTheDocument();
    expect(getNeighbourhood).toHaveBeenCalledWith("sa", { depth: 1, types: RELATION_TYPES });
    expect(screen.getByRole("link", { name: t("graphExplorer.openDocument") })).toHaveAttribute("href", "/v/sa");
    await within(canvas()).findByRole("button", { name: "Doc b" });

    // A leaf is selected but not loaded.
    fireEvent.click(within(canvas()).getByRole("button", { name: "Doc c" }));
    const leaf = await screen.findByRole("region", { name: t("graphExplorer.panelLabel", { title: "Doc c" }) });
    expect(within(leaf).getByText(t("graphExplorer.stateLeaf"))).toBeInTheDocument();
    expect(getNeighbourhood).toHaveBeenCalledTimes(1);

    fireEvent.click(within(canvas()).getByRole("button", { name: "Doc b" }));
    expect(await within(canvas()).findByRole("button", { name: "Doc d" })).toBeInTheDocument();
    expect(getNeighbourhood).toHaveBeenLastCalledWith("sb", { depth: 1, types: RELATION_TYPES });
    const details = screen.getByRole("region", { name: t("graphExplorer.panelLabel", { title: "Doc b" }) });
    expect(within(details).getByRole("link", { name: t("graphExplorer.open") })).toHaveAttribute("href", "/v/sb");

    // Collapse drops the branch; the list of loaded cards follows.
    fireEvent.click(within(details).getByRole("button", { name: t("graphExplorer.collapse") }));
    await waitFor(() => expect(within(canvas()).queryByRole("button", { name: "Doc d" })).toBeNull());
    const list = screen.getByRole("region", { name: t("graphExplorer.listTitle") });
    expect(rowsOf(list)).toEqual(["Doc a", "Doc b", "Doc c"]);
  });

  it("walks the graph to a search result that is not on the canvas yet", async () => {
    searchAssets.mockResolvedValue([{ id: "d", slug: "sd", title: "Doc d" }]);
    findGraphPath.mockResolvedValue({
      path: [
        { kind: "doc", id: "a", slug: "sa", title: "Doc a" },
        { kind: "doc", id: "b", slug: "sb", title: "Doc b" },
        { kind: "doc", id: "d", slug: "sd", title: "Doc d" },
      ],
    });
    renderWithClient(<GraphExplorer doc="sa" />);
    await within(await screen.findByRole("img")).findByRole("button", { name: "Doc b" });

    fireEvent.change(screen.getByRole("combobox", { name: t("graphExplorer.search") }), { target: { value: "Doc d" } });
    fireEvent.click(await screen.findByRole("option", { name: "Doc d" }));

    expect(await within(canvas()).findByRole("button", { name: "Doc d" })).toBeInTheDocument();
    // From what is on the canvas: the expandable documents (c is a leaf).
    expect(findGraphPath).toHaveBeenCalledWith("sd", { from: ["a", "b"], projects: [], types: [...RELATION_TYPES] });
    expect(getNeighbourhood).toHaveBeenCalledWith("sb", { depth: 1, types: RELATION_TYPES });
    // The result is selected, not a new start: the address and the root stay.
    expect(screen.getByRole("region", { name: t("graphExplorer.panelButton") })).toHaveTextContent("Doc d");
    expect(within(canvas()).getByRole("button", { name: "Doc a" })).toBeInTheDocument();
  });

  it("selects a search result already on the canvas without asking for a path", async () => {
    searchAssets.mockResolvedValue([]);
    renderWithClient(<GraphExplorer doc="sa" />);
    await within(await screen.findByRole("img")).findByRole("button", { name: "Doc b" });
    fireEvent.change(screen.getByRole("combobox", { name: t("graphExplorer.search") }), { target: { value: "Doc b" } });
    const option = await screen.findByRole("option", { name: "Doc b" });
    expect(screen.getByText(t("graphExplorer.searchOnCanvas"))).toBeInTheDocument();
    fireEvent.click(option);
    await waitFor(() =>
      expect(screen.getByRole("region", { name: t("graphExplorer.panelButton") })).toHaveTextContent("Doc b"),
    );
    expect(findGraphPath).not.toHaveBeenCalled();
  });

  it("says when no walk reaches a result and offers to start from it", async () => {
    searchAssets.mockResolvedValue([{ id: "z", slug: "sz", title: "Doc z" }]);
    findGraphPath.mockResolvedValue({ path: null });
    renderWithClient(<GraphExplorer doc="sa" />);
    await within(await screen.findByRole("img")).findByRole("button", { name: "Doc b" });
    fireEvent.change(screen.getByRole("combobox", { name: t("graphExplorer.search") }), { target: { value: "Doc z" } });
    fireEvent.click(await screen.findByRole("option", { name: "Doc z" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(t("graphExplorer.unreachable", { title: "Doc z" }));
    expect(screen.getByRole("button", { name: t("graphExplorer.showFromHere") })).toBeInTheDocument();
  });

  it("reports a failed server search even when a matching card is on the canvas", async () => {
    searchAssets.mockRejectedValue(new Error("offline"));
    renderWithClient(<GraphExplorer doc="sa" />);
    await within(await screen.findByRole("img")).findByRole("button", { name: "Doc b" });
    fireEvent.change(screen.getByRole("combobox", { name: t("graphExplorer.search") }), { target: { value: "Doc b" } });
    expect(await screen.findByRole("alert")).toHaveTextContent(t("home.searchFailed"));
    expect(screen.getByRole("option", { name: "Doc b" })).toBeInTheDocument();
    expect(screen.queryByText(t("graphExplorer.searchEmpty"))).toBeNull();
  });

  it("opens cards in a new tab and answers the keyboard shortcuts", async () => {
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    const go = vi.spyOn(nav, "navigate").mockImplementation(() => {});
    renderWithClient(<GraphExplorer doc="sa" />);
    await within(await screen.findByRole("img")).findByRole("button", { name: "Doc b" });

    // Ctrl+click on a row of the loaded list.
    const list = screen.getByRole("region", { name: t("graphExplorer.listTitle") });
    fireEvent.click(within(list).getByRole("button", { name: "Doc b" }), { ctrlKey: true });
    expect(open).toHaveBeenLastCalledWith("/v/sb", "_blank", "noopener,noreferrer");

    fireEvent.click(within(canvas()).getByRole("button", { name: "Doc c" }));
    await screen.findByRole("region", { name: t("graphExplorer.panelLabel", { title: "Doc c" }) });
    fireEvent.keyDown(document.body, { key: "Enter", ctrlKey: true });
    expect(open).toHaveBeenLastCalledWith("/v/sc", "_blank", "noopener,noreferrer");
    fireEvent.keyDown(document.body, { key: "Enter" });
    expect(go).toHaveBeenLastCalledWith("/v/sc");

    // Keys reach the explorer wherever focus is, unless a field holds it.
    fireEvent.keyDown(document.body, { key: "/" });
    expect(screen.getByRole("combobox", { name: t("graphExplorer.search") })).toHaveFocus();
    (document.activeElement as HTMLElement).blur();

    fireEvent.keyDown(screen.getByRole("combobox", { name: t("graphExplorer.search") }), { key: "p" });
    expect(screen.getByRole("region", { name: t("graphExplorer.panelButton") })).toBeInTheDocument();
    const main = document.createElement("main");
    main.tabIndex = -1;
    document.body.append(main);
    fireEvent.keyDown(main, { key: "p" });
    expect(screen.queryByRole("region", { name: t("graphExplorer.panelButton") })).toBeNull();
    main.remove();
    fireEvent.keyDown(document.body, { key: "p" });
    expect(screen.getByRole("region", { name: t("graphExplorer.panelButton") })).toBeInTheDocument();

    // E folds the selected, expanded card.
    fireEvent.click(within(canvas()).getByRole("button", { name: "Doc a" }));
    fireEvent.keyDown(document.body, { key: "e" });
    await waitFor(() => expect(within(canvas()).queryByRole("button", { name: "Doc b" })).toBeNull());
  });

  it("filters the loaded list by title", async () => {
    renderWithClient(<GraphExplorer doc="sa" />);
    await within(await screen.findByRole("img")).findByRole("button", { name: "Doc b" });
    const list = screen.getByRole("region", { name: t("graphExplorer.listTitle") });
    fireEvent.change(within(list).getByRole("searchbox"), { target: { value: "doc c" } });
    await waitFor(() => expect(rowsOf(list)).toEqual(["Doc c"]));
  });

  it("shows no access when the start document cannot be read", async () => {
    getNeighbourhood.mockRejectedValue(new Error("nope"));
    renderWithClient(<GraphExplorer doc="sz" />);
    expect(await screen.findByText(t("viewerStates.noAccess"))).toBeInTheDocument();
  });

  it("mounts only a window of a long list", () => {
    expect(windowOf(0, 0)).toEqual([]);
    expect(windowOf(1000, 0).length).toBeLessThan(40);
    expect(windowOf(1000, 36 * 500)[0]).toBe(492);
  });
});
