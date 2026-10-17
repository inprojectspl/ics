import type { ForceSettings, GraphNode, RenderSettings, SimNode as EngineSimNode } from "../graph";

export type GraphPayload = {
  nodes: Array<{ path: string; title: string; in_degree: number; out_degree: number }>;
  edges: Array<{ from: string; to: string }>;
};

export interface Props {
  /** Stable identity for the data source - graph re-fetches when this
   * changes. Used as a React key into the data-loading effect. */
  source: string;
  /** How to fetch the graph payload. Owner viewer passes
   * `api.getGraph(slug)`, share viewer passes `api.getShareGraph(token)`. */
  fetcher: () => Promise<GraphPayload>;
  /** Called when the user clicks a node to open the corresponding file. */
  onOpenFile: (path: string) => void;
  /** Currently-viewed file (highlighted as the focus node). Optional. */
  currentPath?: string;
}

/** Tunable layout parameters; defaults suit a 50-200 note vault, user
 * overrides persist in localStorage. */
export interface GraphSettings extends ForceSettings, RenderSettings {}

/** A vault note as an engine node; `id` is the note path. */
export interface VaultNode extends GraphNode {
  path: string;
  title: string;
  in_degree: number;
  out_degree: number;
}

export type SimNode = EngineSimNode<VaultNode>;
