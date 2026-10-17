import { describe, expect, it } from "vitest";

import type { ProjectGraphNode } from "../../api/types";
import type { FilteredGraph } from "./filters";
import { buildMapScene, isTaskNodeId, mapGraph, taskNodeId, type MapSceneInput } from "./model";

const doc = (id: string, external = false) =>
  ({ id, slug: id, title: id.toUpperCase(), doc_type: null, freshness: "current", external }) as ProjectGraphNode;

const rel = (id: string, source: string, target: string, type = "derived_from") =>
  ({ id, relation_type: type, source_id: source, target_id: target, origin: "manual" }) as FilteredGraph["edges"][number];

const filtered: FilteredGraph = {
  nodes: [doc("a"), doc("b", true), doc("c"), doc("d")],
  edges: [rel("e1", "b", "a"), rel("e2", "d", "c")],
  unlinked: [doc("loose")],
  componentSizes: [2, 2],
  componentOf: new Map([
    ["a", 0],
    ["b", 0],
    ["c", 1],
    ["d", 1],
  ]),
};

const task = { id: "openproject:work_package:7", system: "openproject", entity: "work_package", external_id: "7", external_scope: null, label: null, url: null };
const links = [
  { task_id: task.id, asset_id: "a", role: "context", required: true },
  { task_id: task.id, asset_id: "c", role: "context", required: false },
  { task_id: task.id, asset_id: "gone", role: "context", required: false },
];

function input(over: Partial<MapSceneInput> = {}): MapSceneInput {
  return {
    filtered,
    showUnlinked: true,
    tasks: [task],
    links,
    showTasks: false,
    mode: "graph",
    density: "normal",
    typeLabel: (key) => key ?? "none",
    ...over,
  };
}

describe("mapGraph", () => {
  it("draws external documents dashed and the unlinked ones in their own group", () => {
    const { cards } = mapGraph(input());
    expect(cards.map((c) => c.id)).toEqual(["a", "b", "c", "d", "loose"]);
    expect(cards.find((c) => c.id === "b")?.dashed).toBe(true);
    expect(cards.find((c) => c.id === "loose")?.component).toBe(-1);
    expect(mapGraph(input({ showUnlinked: false })).cards).toHaveLength(4);
  });

  it("adds tasks on request, joining the graphs they link", () => {
    const { cards, edges } = mapGraph(input({ showTasks: true }));
    const id = taskNodeId(task.id);
    expect(isTaskNodeId(id)).toBe(true);
    const taskCard = cards.find((c) => c.id === id);
    expect(taskCard).toMatchObject({ title: "#7", variant: "task" });
    expect(edges.filter((e) => e.kind === "task")).toHaveLength(2);
    // The task links both graphs, so they are drawn as one group.
    const groups = new Set(cards.filter((c) => c.component >= 0).map((c) => c.component));
    expect(groups.size).toBe(1);
    expect(edges.find((e) => e.target === "a" && e.kind === "task")?.dashed).toBe(false);
  });
});

describe("buildMapScene", () => {
  it("frames each graph and lays the trace out left to right with other relations quiet", () => {
    const graph = buildMapScene(input(), 1.6);
    expect(graph.direction).toBe("down");
    expect(graph.frames).toHaveLength(3);
    const trace = buildMapScene(
      input({ mode: "trace", filtered: { ...filtered, edges: [...filtered.edges, rel("e3", "d", "a", "relates_to")] } }),
      1.6,
    );
    expect(trace.direction).toBe("right");
    expect(trace.edges.find((e) => e.kind === "relates_to")?.quiet).toBe(true);
    expect(trace.edges.find((e) => e.kind === "derived_from")?.quiet).toBeUndefined();
  });
});
