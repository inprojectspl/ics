/**
 * Pure, deterministic building blocks of the Sugiyama-style layout in
 * `cardLayout.ts`: DFS cycle breaking in id order, longest-path layering and
 * barycentric crossing minimisation.
 */
export type Segment = { source: string; target: string };

export type Pair = [string, string];

export function byId(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

/** Appends `value` to the list under `key`, creating it on first use. */
export function pushTo<K, V>(map: Map<K, V[]>, key: K, value: V): void {
  const list = map.get(key);
  if (list) list.push(value);
  else map.set(key, [value]);
}

/** The edges without the back edges a DFS in id order finds: an acyclic set. */
export function breakCycles(nodes: string[], edges: Pair[]): Pair[] {
  const out = new Map<string, string[]>();
  for (const [s, t] of edges) {
    const list = out.get(s);
    if (list) list.push(t);
    else out.set(s, [t]);
  }
  for (const list of out.values()) list.sort(byId);
  const state = new Map<string, 1 | 2>(); // 1 = on stack, 2 = done
  const brokenKeys = new Set<string>();
  // Iterative DFS so long chains cannot overflow the call stack.
  for (const root of nodes) {
    if (state.has(root)) continue;
    const stack: Array<{ id: string; next: number }> = [{ id: root, next: 0 }];
    state.set(root, 1);
    while (stack.length > 0) {
      const top = stack[stack.length - 1];
      if (!top) break;
      const targets = out.get(top.id) ?? [];
      const t = targets[top.next];
      if (t === undefined) {
        state.set(top.id, 2);
        stack.pop();
        continue;
      }
      top.next += 1;
      const st = state.get(t);
      if (st === 1) brokenKeys.add(`${top.id}\u0000${t}`);
      else if (st === undefined) {
        state.set(t, 1);
        stack.push({ id: t, next: 0 });
      }
    }
  }
  return edges.filter((e) => !brokenKeys.has(`${e[0]}\u0000${e[1]}`));
}

/** Longest-path layering: a node sits one column right of its furthest origin. */
export function assignLayers(nodes: string[], dag: Pair[]): Map<string, number> {
  const origins = new Map<string, string[]>();
  for (const [s, t] of dag) {
    const list = origins.get(s);
    if (list) list.push(t);
    else origins.set(s, [t]);
  }
  const layer = new Map<string, number>();
  const visit = (root: string) => {
    const stack: Array<{ id: string; next: number }> = [{ id: root, next: 0 }];
    while (stack.length > 0) {
      const top = stack[stack.length - 1];
      if (!top) break;
      const list = origins.get(top.id) ?? [];
      const t = list[top.next];
      if (t === undefined) {
        let l = 0;
        for (const o of list) l = Math.max(l, (layer.get(o) ?? 0) + 1);
        layer.set(top.id, l);
        stack.pop();
        continue;
      }
      top.next += 1;
      if (!layer.has(t)) stack.push({ id: t, next: 0 });
    }
  };
  for (const id of nodes) if (!layer.has(id)) visit(id);
  return layer;
}

/**
 * Number of edge crossings when layers are drawn as columns and each edge
 * as a straight segment between its endpoints' (layer, row) positions.
 * Edges within one layer and edges sharing an endpoint never count.
 */
export function countCrossings(layers: string[][], edges: Segment[]): number {
  const pos = new Map<string, { l: number; r: number }>();
  for (const [l, col] of layers.entries()) {
    for (const [r, id] of col.entries()) pos.set(id, { l, r });
  }
  const segs: Array<{ a: string; b: string; l0: number; r0: number; l1: number; r1: number }> = [];
  for (const e of edges) {
    const p = pos.get(e.source);
    const q = pos.get(e.target);
    if (!p || !q || p.l === q.l) continue;
    const [lo, hi] = p.l < q.l ? [p, q] : [q, p];
    segs.push({ a: e.source, b: e.target, l0: lo.l, r0: lo.r, l1: hi.l, r1: hi.r });
  }
  const rowAt = (s: (typeof segs)[number], l: number) =>
    s.r0 + ((s.r1 - s.r0) * (l - s.l0)) / (s.l1 - s.l0);
  let crossings = 0;
  // O(E^2) over segment pairs; trace graphs are small.
  for (let i = 0; i < segs.length; i++) {
    const s = segs[i];
    if (!s) continue;
    for (let j = i + 1; j < segs.length; j++) {
      const u = segs[j];
      if (!u) continue;
      if (s.a === u.a || s.a === u.b || s.b === u.a || s.b === u.b) continue;
      const from = Math.max(s.l0, u.l0);
      const to = Math.min(s.l1, u.l1);
      if (from >= to) continue;
      const d0 = rowAt(s, from) - rowAt(u, from);
      const d1 = rowAt(s, to) - rowAt(u, to);
      if (d0 * d1 < 0) crossings += 1;
    }
  }
  return crossings;
}

/** Reorders `layer` by the mean row of each node's neighbours in fixed layers. */
function sortByBarycentre(
  layer: string[],
  neighbours: Map<string, string[]>,
  row: Map<string, number>,
): string[] {
  const keyed = layer.map((id, i) => {
    let sum = 0;
    let n = 0;
    for (const nb of neighbours.get(id) ?? []) {
      const r = row.get(nb);
      if (r === undefined) continue;
      sum += r;
      n += 1;
    }
    // Nodes without fixed neighbours keep their current slot.
    return { id, key: n > 0 ? sum / n : i, i };
  });
  keyed.sort((a, b) => a.key - b.key || a.i - b.i);
  return keyed.map((k) => k.id);
}

export function minimiseCrossings(initial: string[][], edges: Segment[], sweeps: number): string[][] {
  const layerOf = new Map<string, number>();
  for (const [l, col] of initial.entries()) for (const id of col) layerOf.set(id, l);
  const left = new Map<string, string[]>();
  const right = new Map<string, string[]>();
  const link = (m: Map<string, string[]>, k: string, v: string) => {
    const list = m.get(k);
    if (list) list.push(v);
    else m.set(k, [v]);
  };
  for (const e of edges) {
    const ls = layerOf.get(e.source);
    const lt = layerOf.get(e.target);
    if (ls === undefined || lt === undefined || ls === lt) continue;
    const [lo, hi] = ls < lt ? [e.source, e.target] : [e.target, e.source];
    link(left, hi, lo);
    link(right, lo, hi);
  }
  const layers = initial.map((c) => [...c]);
  let best = layers.map((c) => [...c]);
  let bestCount = countCrossings(best, edges);
  for (let s = 0; s < sweeps && bestCount > 0; s++) {
    const row = new Map<string, number>();
    const fix = (col: string[]) => col.forEach((id, r) => row.set(id, r));
    const first = layers[0];
    if (first) fix(first);
    for (let l = 1; l < layers.length; l++) {
      const next = sortByBarycentre(layers[l] ?? [], left, row);
      layers[l] = next;
      fix(next);
    }
    row.clear();
    const last = layers[layers.length - 1];
    if (last) fix(last);
    for (let l = layers.length - 2; l >= 0; l--) {
      const next = sortByBarycentre(layers[l] ?? [], right, row);
      layers[l] = next;
      fix(next);
    }
    const count = countCrossings(layers, edges);
    if (count < bestCount) {
      bestCount = count;
      best = layers.map((c) => [...c]);
    }
  }
  return best;
}
