import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

import type { Neighbourhood, NeighbourhoodNode, RelationEdge } from "../../api";
import { RELATION_TYPES } from "../../api/relationTypes";
import { t, tn } from "../../lib/i18n";
import { GraphLegend } from "./GraphLegend";
import { RelationsInspector } from "./RelationsInspector";
import { toMiniGraph } from "./miniGraphData";

const loaded = vi.hoisted(() => ({ miniGraph: false }));
const getNeighbourhood = vi.fn();

vi.mock("./MiniGraph", async (importOriginal) => {
  loaded.miniGraph = true;
  return importOriginal();
});
vi.mock("../../api", () => ({
  api: {
    getNeighbourhood: (...a: unknown[]) => getNeighbourhood(...a),
    listDocTypes: () => Promise.resolve([]),
  },
}));

function node(id: string, over: Partial<NeighbourhoodNode> = {}): NeighbourhoodNode {
  return {
    id,
    slug: `s${id}`,
    title: `Doc ${id}`,
    kind: "md_single",
    doc_type: null,
    freshness: "current",
    summary: null,
    estimated_tokens: null,
    depth: id === "a" ? 0 : 1,
    expandable: true,
    ...over,
  };
}

function edge(id: string, source: string, target: string): RelationEdge {
  return {
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
    origin: "extracted",
    created_at: null,
  };
}

const hood: Neighbourhood = {
  root_id: "a",
  depth: 1,
  types: ["derived_from"],
  nodes: [node("a"), node("b", { freshness: "superseded" }), node("c")],
  edges: [edge("e1", "a", "b"), edge("e2", "c", "a")],
  truncated: false,
  max_nodes: 50,
};

function wrap(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  getNeighbourhood.mockReset().mockResolvedValue(hood);
  // jsdom has no 2D context; the engine skips drawing without one.
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
});

afterEach(() => vi.restoreAllMocks());

describe("MiniGraph", () => {
  it("is loaded only after switching the relations tab to the graph, which is remembered", async () => {
    localStorage.removeItem("ics-relations-mode");
    const { unmount } = render(wrap(<RelationsInspector slug="sa" assetId="a" canEdit={false} />));
    expect(loaded.miniGraph).toBe(false);
    expect(getNeighbourhood).not.toHaveBeenCalled();
    expect(screen.getByRole("link", { name: t("relations.openGraph") })).toHaveAttribute("href", "/graph?doc=sa");

    fireEvent.click(screen.getByRole("radio", { name: t("relations.modeGraph") }));

    expect(await screen.findByRole("img", { name: /3/ })).toBeInTheDocument();
    expect(loaded.miniGraph).toBe(true);
    expect(getNeighbourhood).toHaveBeenCalledWith("sa", { depth: 1, types: RELATION_TYPES });
    unmount();

    render(wrap(<RelationsInspector slug="sa" assetId="a" canEdit={false} />));
    expect(await screen.findByRole("img", { name: /3/ })).toBeInTheDocument();
  });

  it("names the canvas with its node and edge counts and shows only direct neighbours", async () => {
    const { MiniGraph } = await import("./MiniGraph");
    render(wrap(<MiniGraph slug="sa" />));
    const label = `${t("miniGraph.label")}: ${tn("miniGraph.nodes", 3)}, ${tn("miniGraph.edges", 2)}`;
    expect(await screen.findByRole("img", { name: label })).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: "2" })).toBeNull();
    await waitFor(() => expect(getNeighbourhood).toHaveBeenCalledTimes(1));
  });
});

describe("GraphLegend", () => {
  it("names each drawn doc type and relation type once", () => {
    const g = toMiniGraph(hood, (key) => key ?? "No type");
    render(<GraphLegend cards={g.cards} edges={g.edges} />);
    expect(screen.getAllByText("No type")).toHaveLength(1);
    expect(screen.getAllByText(t("relation.derivedFrom"))).toHaveLength(1);
  });
});

describe("toMiniGraph", () => {
  it("turns the neighbourhood into cards with slugs and styled, named edges", () => {
    const g = toMiniGraph(hood, (key) => key ?? "none");
    expect(g.cards.map((c) => c.id)).toEqual(["a", "b", "c"]);
    expect(g.cards.find((c) => c.id === "b")?.muted).toBe(true);
    expect(g.slugs.get("c")).toBe("sc");
    expect(g.edges).toHaveLength(2);
    expect(g.edges[0]).toMatchObject({ source: "a", target: "b", kind: "derived_from" });
  });
});
