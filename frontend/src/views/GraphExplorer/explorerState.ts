/**
 * What the reader has done in the explorer: which nodes are expanded (in
 * order), how many pages of children each shows, and when each branch was
 * last used. Transitions are pure; the budget collapses the least recently
 * used branches when the canvas would hold too many cards.
 */
import { ancestorsOf, subtreeOf, type ExploredTree, type Expansion } from "./explorerTree";

/** Cards kept in the browser at most; past it, old branches are collapsed. */
const MAX_CARDS = 500;

export interface ExplorerState {
  expansions: Expansion[];
  reveal: Record<string, number>;
  /** Cards kept on the canvas past their parent's page: the steps of walks to search results. */
  pinned: string[];
  /** Logical time of the last use (expand, reveal, select) per expanded node. */
  used: Record<string, number>;
  clock: number;
  /** Branches the last budget check collapsed; the view tells the reader. */
  evicted: number;
}

export function initialState(expansions: Expansion[] = []): ExplorerState {
  const used: Record<string, number> = {};
  for (const [i, e] of expansions.entries()) used[e.id] = i + 1;
  return { expansions, reveal: {}, pinned: [], used, clock: expansions.length, evicted: 0 };
}

function isExpanded(state: ExplorerState, id: string): boolean {
  return state.expansions.some((e) => e.id === id);
}

/** Marks the node and its expanded ancestors as just used. */
export function touch(state: ExplorerState, tree: ExploredTree, id: string): ExplorerState {
  const clock = state.clock + 1;
  const used = { ...state.used };
  let changed = false;
  for (const a of ancestorsOf(tree, id)) {
    if (a in used) {
      used[a] = clock;
      changed = true;
    }
  }
  return changed ? { ...state, used, clock } : state;
}

export function expand(state: ExplorerState, exp: Expansion): ExplorerState {
  if (isExpanded(state, exp.id)) return state;
  const clock = state.clock + 1;
  return {
    ...state,
    expansions: [...state.expansions, exp],
    used: { ...state.used, [exp.id]: clock },
    clock,
  };
}

/** Collapses the node: its expansion and every expansion under it are dropped. */
export function collapse(state: ExplorerState, tree: ExploredTree, id: string): ExplorerState {
  const gone = new Set(subtreeOf(tree, id));
  gone.add(id);
  const reveal = { ...state.reveal };
  const used = { ...state.used };
  for (const g of gone) {
    delete reveal[g];
    delete used[g];
  }
  return {
    ...state,
    expansions: state.expansions.filter((e) => !gone.has(e.id)),
    reveal,
    // The collapsed node keeps its own pin: it is still on the canvas.
    pinned: state.pinned.filter((p) => p === id || !gone.has(p)),
    used,
  };
}

/** Shows the next page of the node's children. */
export function revealMore(state: ExplorerState, id: string): ExplorerState {
  const clock = state.clock + 1;
  return {
    ...state,
    reveal: { ...state.reveal, [id]: (state.reveal[id] ?? 0) + 1 },
    used: id in state.used ? { ...state.used, [id]: clock } : state.used,
    clock,
  };
}

/**
 * Collapses the least recently used expanded branches until the tree fits
 * `max` cards. Branches holding a protected node (the selection, the node
 * just expanded) are kept, so the tree may stay over the budget when
 * nothing else is left. Returns the collapsed node ids, oldest first.
 */
export function enforceBudget(
  state: ExplorerState,
  build: (s: ExplorerState) => ExploredTree,
  protect: ReadonlyArray<string | null>,
  max: number = MAX_CARDS,
): { state: ExplorerState; collapsed: string[] } {
  let s = state;
  const collapsed: string[] = [];
  for (;;) {
    const tree = build(s);
    if (tree.nodes.size <= max) break;
    const keep = new Set(protect.flatMap((id) => ancestorsOf(tree, id)));
    let victim: string | null = null;
    let oldest = Infinity;
    for (const e of s.expansions) {
      const node = tree.nodes.get(e.id);
      if (!node?.expanded || keep.has(e.id)) continue;
      const at = s.used[e.id] ?? 0;
      if (at < oldest) {
        oldest = at;
        victim = e.id;
      }
    }
    if (victim === null) break;
    s = collapse(s, tree, victim);
    collapsed.push(victim);
  }
  return { state: { ...s, evicted: collapsed.length }, collapsed };
}

/**
 * Opens a walk to a search result: every step but the last is expanded,
 * in order, and every step but the first is pinned so no "more" card hides
 * it. Steps already expanded stay as they are.
 */
export function walk(state: ExplorerState, steps: readonly Expansion[], target: string): ExplorerState {
  let next = state;
  for (const step of steps) next = expand(next, step);
  const pins = new Set(next.pinned);
  for (const step of steps.slice(1)) pins.add(step.id);
  pins.add(target);
  return { ...next, pinned: [...pins] };
}
