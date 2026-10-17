/**
 * Data model of the graph engine. Plain nodes and edges keyed by string id,
 * independent of where the graph comes from (collections, document trace).
 */

/** Optional per-node visual overrides; omitted fields use the theme defaults. */
interface NodeStyle {
  /** Fill colour. */
  color?: string;
  /** Outline colour. */
  border?: string;
  /** Drawn translucent, e.g. filtered out but kept for context. */
  faded?: boolean;
  /** Dashed outline. */
  dashed?: boolean;
  /** Emphasised like the current node: accent fill, label always shown. */
  highlighted?: boolean;
}

/** Optional per-edge visual overrides. */
export interface EdgeStyle {
  color?: string;
  faded?: boolean;
  dashed?: boolean;
  /** Line width in world units; 1 when omitted. */
  width?: number;
  /** Drawn like an edge of the hovered node. */
  highlighted?: boolean;
}

export interface GraphNode {
  id: string;
  label: string;
  /** Drives the radius. Computed from the edge list when omitted. */
  degree?: number;
  style?: NodeStyle;
}

export interface GraphEdge {
  /** For `derived_from`: the derived node (drawn to the right in layered layouts). */
  source: string;
  target: string;
  /** Relation kind, e.g. `derived_from`. */
  kind?: string;
  style?: EdgeStyle;
}

/** A node with physics state. Extra fields of `N` are carried through. */
export type SimNode<N extends GraphNode = GraphNode> = N & {
  x: number;
  y: number;
  vx: number;
  vy: number;
  /** Pinned by user drag - not updated by physics until released. */
  pinned: boolean;
  /** Total degree, cached for radius. */
  degree: number;
};

export interface SimEdge {
  fromIdx: number;
  toIdx: number;
  style?: EdgeStyle;
}

export interface Transform {
  x: number;
  y: number;
  zoom: number;
}

export interface Size {
  w: number;
  h: number;
}

/** Force model knobs, see `stepSimulation`. */
export interface ForceSettings {
  /** Coulomb-style point repulsion. Higher = nodes push harder apart. */
  repulsion: number;
  /** Rest length of the springs along edges (px in world space). */
  linkDistance: number;
  /** Spring stiffness for edges. Higher = edges contract faster. */
  linkForce: number;
  /** Pull every node toward the canvas centre. */
  centerForce: number;
}

/** Drawing knobs, see `drawScene`. */
export interface RenderSettings {
  /** Multiplier applied to node radius computed from degree. */
  nodeScale: number;
  /** When to render text labels on nodes. */
  labels: "always" | "hover" | "off";
  /** Draw a small arrow head at the target end of every edge. */
  showArrows: boolean;
}
