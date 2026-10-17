/** A node of the sign-in backdrop: a small disc drifting on its own. */
export interface DriftNode {
  x: number;
  y: number;
  vx: number;
  vy: number;
  r: number;
  /** Drawn in the brand colour, echoing the nodes of the ICS mark. */
  brand: boolean;
}

export const NODE_COUNT = 36;
/** Every n-th node carries the brand colour; the rest stay neutral. */
const BRAND_EVERY = 7;
const MAX_SPEED = 0.35;
const KICK = 0.006;
/** How far past an edge a node travels before it re-enters on the other side. */
const WRAP_MARGIN = 10;

export function seedNodes(w: number, h: number, random: () => number = Math.random): DriftNode[] {
  return Array.from({ length: NODE_COUNT }, (_, i) => ({
    x: random() * w,
    y: random() * h,
    vx: (random() - 0.5) * 0.3,
    vy: (random() - 0.5) * 0.3,
    // Most nodes land small (about 1.2-2 px), a few larger: reads as organic.
    r: 1.2 + Math.pow(random(), 1.6) * 2,
    brand: i % BRAND_EVERY === 0,
  }));
}

/**
 * One frame of drift: a tiny random kick, a speed cap so the motion stays
 * leisurely, and wrap-around at the edges. No pull towards the centre, so
 * the nodes never clump behind the card.
 */
export function stepNodes(nodes: DriftNode[], w: number, h: number, random: () => number = Math.random): void {
  for (const n of nodes) {
    n.vx += (random() - 0.5) * KICK;
    n.vy += (random() - 0.5) * KICK;
    const v = Math.hypot(n.vx, n.vy);
    if (v > MAX_SPEED) {
      n.vx = (n.vx / v) * MAX_SPEED;
      n.vy = (n.vy / v) * MAX_SPEED;
    }
    n.x += n.vx;
    n.y += n.vy;
    if (n.x < -WRAP_MARGIN) n.x = w + WRAP_MARGIN;
    else if (n.x > w + WRAP_MARGIN) n.x = -WRAP_MARGIN;
    if (n.y < -WRAP_MARGIN) n.y = h + WRAP_MARGIN;
    else if (n.y > h + WRAP_MARGIN) n.y = -WRAP_MARGIN;
  }
}

/** Moves the nodes with a resized viewport, so none are left off screen. */
export function scaleNodes(nodes: DriftNode[], sx: number, sy: number): void {
  for (const n of nodes) {
    n.x *= sx;
    n.y *= sy;
  }
}

/** Link strength for a pair: 1 when touching, 0 at `maxDist` and beyond. */
export function linkStrength(a: DriftNode, b: DriftNode, maxDist: number): number {
  const dSq = (a.x - b.x) ** 2 + (a.y - b.y) ** 2;
  const maxSq = maxDist * maxDist;
  return dSq >= maxSq ? 0 : 1 - dSq / maxSq;
}
