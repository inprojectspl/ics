import { Suspense } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { Me, ProjectGraph, ProjectGraphNode, RelationEdge } from "../../api";
import { ProjectTabs } from "../../components/ProjectTabs";
import { t } from "../../lib/i18n";
import { ProjectDocumentMapLazy } from "./lazy";
import { NodeList } from "./NodeList";
import { ProjectDocumentMap } from "./ProjectDocumentMap";
import { renderWithClient } from "../../test-utils";

const getProjectGraph = vi.fn();

vi.mock("../../api", () => ({
  api: {
    getProjectGraph: (...a: unknown[]) => getProjectGraph(...a),
    listProjects: vi.fn().mockResolvedValue({ items: [], total: 0, page: 1, page_size: 200 }),
  },
}));
vi.mock("../../lib/useDocTypes", () => ({
  useDocTypeLabels: () => new Map([["design", "Design"]]),
  useDocTypeLabel: () => (key: string | null) => key ?? "",
  useDocTypes: () => [],
}));
// jsdom has no canvas; the map's accessible name is what matters here.
vi.mock("./MapCanvas", () => ({
  MapCanvas: ({ label, panel }: { label: string; panel?: React.ReactNode }) => (
    <>
      <div role="img" aria-label={label} />
      {panel}
    </>
  ),
}));

const me = { id: "u1", email: "a@example.com", display_name: null, role: "user" } as Me;

function node(id: string, title: string, over: Partial<ProjectGraphNode> = {}): ProjectGraphNode {
  return {
    id,
    slug: `s${id}`,
    title,
    kind: "md_file",
    doc_type: "design",
    freshness: "current",
    summary: `Summary of ${title}`,
    estimated_tokens: 1200,
    superseded_by: null,
    content_updated_at: null,
    external: false,
    ...over,
  } as ProjectGraphNode;
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

const graph: ProjectGraph = {
  project: { id: "p", slug: "p1", name: "Apollo" },
  nodes: [
    node("a", "Goals"),
    node("b", "Requirements"),
    node("c", "Design"),
    node("x", "Loose note"),
  ],
  edges: [edge("ba", "b", "a"), edge("cb", "c", "b")],
  truncated: false,
  max_nodes: 1000,
  tasks: [],
  task_links: [],
};

beforeEach(() => {
  getProjectGraph.mockReset().mockResolvedValue(graph);
});

describe("ProjectDocumentMap", () => {
  it("loads lazily", async () => {
    renderWithClient(
      <Suspense fallback={<p>lazy-fallback</p>}>
        <ProjectDocumentMapLazy me={me} slug="p1" />
      </Suspense>,
    );
    expect(screen.getByText("lazy-fallback")).toBeInTheDocument();
    expect(await screen.findByRole("img")).toBeInTheDocument();
    expect(getProjectGraph).toHaveBeenCalledWith("p1", { tasks: true });
  });

  it("links the map from the project tabs for members only", () => {
    const { rerender } = renderWithClient(<ProjectTabs slug="p1" tab="files" member />);
    const nav = screen.getByRole("navigation", { name: t("projectTabs.label") });
    expect(within(nav).getByRole("link", { name: t("projectTabs.map") })).toHaveAttribute(
      "href",
      "/projects/p1/map",
    );
    rerender(<ProjectTabs slug="p1" tab="files" member={false} />);
    expect(screen.queryByRole("navigation", { name: t("projectTabs.label") })).toBeNull();
  });

  it("names the canvas with counts and lists documents without relations aside", async () => {
    renderWithClient(<ProjectDocumentMap me={me} slug="p1" />);
    const canvas = await screen.findByRole("img");
    expect(canvas).toHaveAttribute(
      "aria-label",
      t("projectMap.canvasLabel", { nodes: 3, edges: 2, graphs: 1 }),
    );
    // The lists under the canvas start folded.
    expect(screen.queryByRole("list", { name: t("projectMap.unlinkedList") })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: t("projectMap.unlinked", { count: 1 }) }));
    const unlinked = screen.getByRole("list", { name: t("projectMap.unlinkedList") });
    expect(within(unlinked).getByRole("button", { name: /Loose note/ })).toBeInTheDocument();
  });

  it("filters the map from the toolbar popover", async () => {
    renderWithClient(<ProjectDocumentMap me={me} slug="p1" />);
    await screen.findByRole("img");
    fireEvent.click(screen.getByRole("button", { name: t("filters.title") }));
    const panel = screen.getByRole("dialog", { name: t("projectMap.filters") });
    fireEvent.change(within(panel).getByRole("searchbox", { name: t("projectMap.search") }), {
      target: { value: "Design" },
    });
    await waitFor(() =>
      expect(screen.getByRole("img")).toHaveAttribute(
        "aria-label",
        t("projectMap.canvasLabel", { nodes: 0, edges: 0, graphs: 0 }),
      ),
    );
    // The active filter is counted on the button.
    expect(screen.getByRole("button", { name: new RegExp(`${t("filters.title")}\\s*1`) })).toBeInTheDocument();
  });

  it("opens the node panel from the keyboard", async () => {
    renderWithClient(<ProjectDocumentMap me={me} slug="p1" />);
    fireEvent.click(await screen.findByRole("button", { name: t("projectMap.onMap", { count: 3 }) }));
    const list = await screen.findByRole("list", { name: t("projectMap.onMapList") });
    const rows = within(list).getAllByRole("button");
    expect(rows[0]).toHaveAttribute("tabindex", "0");
    expect(rows[1]).toHaveAttribute("tabindex", "-1");

    rows[0]!.focus();
    fireEvent.keyDown(rows[0]!, { key: "ArrowDown" });
    await waitFor(() => expect(rows[1]).toHaveFocus());
    expect(rows[1]).toHaveAttribute("tabindex", "0");

    fireEvent.keyDown(rows[1]!, { key: "Enter" });
    const panel = await screen.findByRole("complementary", {
      name: t("projectMap.panelLabel", { title: "Requirements" }),
    });
    expect(within(panel).getByText("Summary of Requirements")).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: t("common.open") })).toHaveAttribute("href", "/v/sb");
    // Relations in the panel lead to the neighbours.
    fireEvent.click(within(panel).getByRole("button", { name: "Goals" }));
    expect(
      await screen.findByRole("complementary", { name: t("projectMap.panelLabel", { title: "Goals" }) }),
    ).toBeInTheDocument();
  });

  it("mounts only a window of a long list and keeps keyboard reach to the end", async () => {
    const many = Array.from({ length: 250 }, (_, i) => node(`n${i}`, `Doc ${i}`));
    const onOpen = vi.fn();
    renderWithClient(<NodeList nodes={many} label="many" selectedId={null} onOpen={onOpen} />);
    const list = screen.getByRole("list", { name: "many" });
    const first = within(list).getAllByRole("button")[0]!;
    expect(within(list).getAllByRole("button").length).toBeLessThan(50);
    first.focus();
    fireEvent.keyDown(first, { key: "End" });
    const last = await within(list).findByRole("button", { name: /Doc 249/ });
    await waitFor(() => expect(last).toHaveFocus());
    fireEvent.keyDown(last, { key: " " });
    expect(onOpen).toHaveBeenCalledWith("n249");
  });
});
