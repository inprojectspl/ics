/**
 * Ordering heuristics of the layered card layout, on top of the barycentric
 * sweeps in `layered.ts`. Pure and deterministic.
 */
import { byId, countCrossings, pushTo, type Segment } from "./layered";

/**
 * Starting order of every layer: DFS discovery order over the undirected
 * graph, so connected cards start adjacent; an id order settles the sweeps in
 * a worse local minimum. Placeholders follow the card their edge starts from.
 */
export function initialOrder(
  layers: string[][],
  links: ReadonlyArray<readonly [string, string]>,
  rank: (id: string) => number,
  ownerOf: (id: string) => string | undefined,
): string[][] {
  const adj = new Map<string, string[]>();
  for (const [a, b] of links) {
    pushTo(adj, a, b);
    pushTo(adj, b, a);
  }
  const byRank = (a: string, b: string) =>
    rank(a) - rank(b) || (adj.get(b)?.length ?? 0) - (adj.get(a)?.length ?? 0) || byId(a, b);
  for (const list of adj.values()) list.sort(byRank);
  const seen = new Map<string, number>();
  const real = layers.flat().filter((id) => ownerOf(id) === undefined).sort(byRank);
  for (const root of real) {
    if (seen.has(root)) continue;
    const stack = [root];
    while (stack.length > 0) {
      const id = stack.pop();
      if (id === undefined || seen.has(id)) continue;
      seen.set(id, seen.size);
      const next = adj.get(id) ?? [];
      for (let i = next.length - 1; i >= 0; i--) {
        const nb = next[i];
        if (nb !== undefined && !seen.has(nb)) stack.push(nb);
      }
    }
  }
  const key = (id: string) => {
    const owner = ownerOf(id);
    return owner === undefined ? (seen.get(id) ?? 0) : (seen.get(owner) ?? 0) + 0.5;
  };
  return layers.map((col) => [...col].sort((a, b) => key(a) - key(b)));
}

/**
 * Moves cards linked within one layer next to each other when that adds no
 * crossing, so such a link is a short hop instead of a line along the row.
 */
export function pullTogether(
  layers: string[][],
  pairs: ReadonlyArray<readonly [string, string]>,
  segments: Segment[],
): string[][] {
  let out = layers.map((c) => [...c]);
  let crossings = countCrossings(out, segments);
  for (const [a, b] of pairs) {
    const l = out.findIndex((col) => col.includes(a));
    const col = out[l];
    if (!col || !col.includes(b)) continue;
    if (Math.abs(col.indexOf(a) - col.indexOf(b)) <= 1) continue;
    let best: string[][] | null = null;
    let bestCount = crossings;
    for (const side of [0, 1]) {
      const rest = col.filter((id) => id !== b);
      rest.splice(rest.indexOf(a) + side, 0, b);
      const trial = out.map((c, i) => (i === l ? rest : c));
      const count = countCrossings(trial, segments);
      if (count <= bestCount) {
        bestCount = count;
        best = trial;
      }
    }
    if (best) {
      out = best;
      crossings = bestCount;
    }
  }
  return out;
}

/**
 * Swaps neighbours within a layer while that removes crossings with the
 * layers on either side: the local refinement the barycentre sweeps miss.
 * Each swap is judged on the two cards' own edges only, so a pass is cheap.
 */
export function transpose(layers: string[][], segments: Segment[], passes = 6): string[][] {
  const out = layers.map((c) => [...c]);
  const layerOf = new Map<string, number>();
  for (const [l, col] of out.entries()) for (const id of col) layerOf.set(id, l);
  const up = new Map<string, string[]>();
  const down = new Map<string, string[]>();
  for (const { source, target } of segments) {
    const ls = layerOf.get(source);
    const lt = layerOf.get(target);
    if (ls === undefined || lt === undefined || ls === lt) continue;
    const [hi, lo] = ls < lt ? [source, target] : [target, source];
    pushTo(down, hi, lo);
    pushTo(up, lo, hi);
  }
  const pos = new Map<string, number>();
  for (const col of out) col.forEach((id, i) => pos.set(id, i));
  // Crossings between the edges of u and v (to one side) with u placed before v.
  const cross = (u: string, v: string, side: Map<string, string[]>) => {
    let n = 0;
    for (const a of side.get(u) ?? []) {
      const pa = pos.get(a) ?? 0;
      for (const b of side.get(v) ?? []) if (pa > (pos.get(b) ?? 0)) n += 1;
    }
    return n;
  };
  for (let pass = 0; pass < passes; pass++) {
    let improved = false;
    for (const col of out) {
      for (let i = 0; i + 1 < col.length; i++) {
        const u = col[i];
        const v = col[i + 1];
        if (u === undefined || v === undefined) continue;
        const before = cross(u, v, up) + cross(u, v, down);
        const after = cross(v, u, up) + cross(v, u, down);
        if (after < before) {
          col[i] = v;
          col[i + 1] = u;
          pos.set(u, i + 1);
          pos.set(v, i);
          improved = true;
        }
      }
    }
    if (!improved) break;
  }
  return out;
}
