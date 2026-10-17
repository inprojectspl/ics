/**
 * Data model of the card graph: documents drawn as cards, grouped into
 * framed clusters, with edges routed between them. Independent of React and
 * of the canvas, so layout and hit testing are testable on their own.
 */
import type { Point } from "./interactions";

export type Density = "compact" | "normal" | "detailed";

export interface CardSize {
  w: number;
  h: number;
}

/** Card geometry per density, in world units (1 unit = 1 CSS px at 100%). */
export const CARD_SIZES: Readonly<Record<Density, CardSize>> = {
  compact: { w: 200, h: 58 },
  normal: { w: 216, h: 96 },
  detailed: { w: 248, h: 120 },
};

export type BadgeTone = "warn" | "mute" | "info";

/** One card as the caller describes it; all text is already localised. */
export interface CardNode {
  id: string;
  title: string;
  /** Small upper line, e.g. the doc type label. */
  kicker?: string;
  /** Extra line shown at the detailed density, e.g. the summary. */
  sub?: string;
  /** Stripe and tile colour. */
  color: string;
  badge?: { text: string; tone: BadgeTone };
  /** Drawn quieter with a struck-through title (superseded). */
  muted?: boolean;
  /** Dashed outline (outside the project, or a task). */
  dashed?: boolean;
  variant?: "doc" | "task";
  /** Independent graph the card belongs to; -1 puts it in the unlinked frame. */
  component: number;
}

export interface CardEdge {
  id: string;
  source: string;
  target: string;
  kind: string;
  color?: string;
  /** Line width in world units. */
  width: number;
  dashed?: boolean;
  /** Shown on the edge while one of its ends is hovered or selected. */
  label?: string;
  /** Context only: drawn faint until one of its ends is in focus. */
  quiet?: boolean;
}

export interface PlacedCard extends CardNode {
  x: number;
  y: number;
  w: number;
  h: number;
}

/**
 * How an edge is drawn: `flow` is a chain of smooth curves along the layer
 * axis, `loop` an orthogonal detour through the gap next to one row, `side`
 * a straight segment between two neighbours in a row.
 */
type RouteShape = "flow" | "loop" | "side";

export interface RoutedEdge extends CardEdge {
  /** From the source end to the target end. */
  points: Point[];
  shape: RouteShape;
}

export interface Frame {
  x: number;
  y: number;
  w: number;
  h: number;
  label: string;
  /** Muted suffix after the label, e.g. the document count. */
  count?: string;
}

export type Direction = "down" | "right";

export interface CardScene {
  /** What a close-up card shows: the title only (compact) or more lines. */
  density: Density;
  cards: PlacedCard[];
  edges: RoutedEdge[];
  frames: Frame[];
  width: number;
  height: number;
  direction: Direction;
}

/** Key of an unordered card pair: parallel edges share it whatever their direction. */
export function pairKey(a: string, b: string): string {
  return a < b ? `${a}\u0000${b}` : `${b}\u0000${a}`;
}

/** Height of the title strip reserved above every frame's content. */
export const FRAME_HEADER = 60;
/** Space between a frame's outline and its cards. */
export const FRAME_PAD = 20;
