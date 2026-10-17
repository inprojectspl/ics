/**
 * Turns the filtered project graph into a card scene: documents (and, on
 * request, tasks) as cards, one framed group per independent graph, the
 * documents without relations in a frame of their own. Pure apart from the
 * catalogue lookups, so it is testable without a canvas.
 */
import type { DocType, ProjectTask, ProjectTaskLink } from "../../api/types";
import {
  CARD_SIZES,
  documentCard,
  LAYER_RELATIONS,
  layoutCardScene,
  relationCardEdge,
  type CardEdge,
  type CardNode,
  type CardScene,
  type Density,
} from "../../components/graph";
import { refNumber } from "../../components/TaskLinks/taskRef";
import { t, tn } from "../../lib/i18n";
import { components, type FilteredGraph } from "./filters";

/** `graph`: groups layered by every directed relation; `trace`: the derivation chain left to right. */
export type MapMode = "graph" | "trace";

const TASK_PREFIX = "task:";
export const TASK_EDGE_COLOR = "#64748b";

// Row limits tried for crowded layers; the one that fills the canvas best wins.
const GRAPH_ROWS = [8, 11, 14];
const TRACE_ROWS = [8, 12, 16];

// A task sits under the documents it links, like a document derived from them.
const GRAPH_LAYERS: ReadonlySet<string> = new Set([...LAYER_RELATIONS, "task"]);
const TRACE_LAYERS: ReadonlySet<string> = new Set(["derived_from", "task"]);

export function taskNodeId(taskId: string): string {
  return TASK_PREFIX + taskId;
}

export function isTaskNodeId(id: string): boolean {
  return id.startsWith(TASK_PREFIX);
}

export interface MapSceneInput {
  filtered: FilteredGraph;
  /** Draw the documents without relations in their own frame. */
  showUnlinked: boolean;
  tasks: ProjectTask[];
  links: ProjectTaskLink[];
  showTasks: boolean;
  mode: MapMode;
  density: Density;
  typeLabel: (docType: DocType | null) => string;
}

function taskCards(
  docs: ReadonlySet<string>,
  tasks: ProjectTask[],
  links: ProjectTaskLink[],
): { cards: CardNode[]; edges: CardEdge[] } {
  const byId = new Map(tasks.map((x) => [x.id, x]));
  const cards: CardNode[] = [];
  const edges: CardEdge[] = [];
  const added = new Set<string>();
  for (const link of links) {
    const task = byId.get(link.task_id);
    if (!task || !docs.has(link.asset_id)) continue;
    const id = taskNodeId(task.id);
    if (!added.has(id)) {
      added.add(id);
      const ref = refNumber(task);
      cards.push({
        id,
        title: task.label || ref,
        kicker: t("projectMap.taskKicker", { ref }),
        color: TASK_EDGE_COLOR,
        variant: "task",
        dashed: true,
        component: 0,
      });
    }
    edges.push({
      id: `${id}>${link.asset_id}`,
      source: id,
      target: link.asset_id,
      kind: "task",
      color: TASK_EDGE_COLOR,
      width: link.required ? 1.6 : 1.1,
      dashed: !link.required,
      label: link.required ? t("projectMap.required") : undefined,
    });
  }
  return { cards, edges };
}

/** Cards and edges of the map before layout; exported for tests. */
export function mapGraph(input: MapSceneInput): { cards: CardNode[]; edges: CardEdge[] } {
  const { filtered } = input;
  const docs = filtered.nodes;
  let cards: CardNode[] = docs.map((n) => documentCard(n, 0, input.typeLabel));
  let edges: CardEdge[] = filtered.edges.map(relationCardEdge);
  if (input.showTasks) {
    const extra = taskCards(new Set(docs.map((n) => n.id)), input.tasks, input.links);
    cards = cards.concat(extra.cards);
    edges = edges.concat(extra.edges);
  }
  // Tasks can join two graphs, so groups are counted again over what is drawn.
  const { of } = components(
    cards.map((c) => c.id),
    edges.map((e) => ({ source_id: e.source, target_id: e.target })),
  );
  for (const c of cards) c.component = of.get(c.id) ?? 0;
  if (input.showUnlinked) {
    for (const n of filtered.unlinked) cards.push(documentCard(n, -1, input.typeLabel));
  }
  return { cards, edges };
}

/** Name of a group: its most connected first-layer document, plus the count. */
function frameTitle(members: CardNode[], root: CardNode | undefined) {
  const docs = members.filter((m) => m.variant !== "task").length;
  return { label: root?.title ?? "", count: tn("format.documentCount", docs) };
}

export function buildMapScene(input: MapSceneInput, aspect: number): CardScene {
  const graph = mapGraph(input);
  const trace = input.mode === "trace";
  // The trace follows derivation; other relations stay as faint context.
  const edges = trace
    ? graph.edges.map((e) => (TRACE_LAYERS.has(e.kind) ? e : { ...e, quiet: true }))
    : graph.edges;
  return layoutCardScene(graph.cards, edges, {
    size: CARD_SIZES[input.density],
    density: input.density,
    direction: trace ? "right" : "down",
    layerKinds: trace ? TRACE_LAYERS : GRAPH_LAYERS,
    frameTitle,
    unlinkedTitle: (count) => ({ label: t("projectMap.unlinkedFrame"), count: tn("format.documentCount", count) }),
    aspect,
    maxPerRow: trace ? TRACE_ROWS : GRAPH_ROWS,
  });
}
