import { useCallback, useMemo, useState } from "react";
import { useQueries, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api";
import type { GraphPathStep, RelationType } from "../../api/types";
import { formatApiError } from "../../lib/apiError";
import { sourceQuery, toLoaded, type SourceData } from "./explorerData";
import {
  collapse,
  enforceBudget,
  expand,
  initialState,
  revealMore,
  touch,
  walk,
  type ExplorerState,
} from "./explorerState";
import {
  buildTree,
  moreParent,
  projectNodeId,
  sourceOf,
  type ExplorerItem,
  type Expansion,
  type ExploredTree,
  type Loaded,
} from "./explorerTree";

const NO_PENDING: ReadonlySet<string> = new Set();

/** A document the search picked: where the walk should end. */
export interface WalkTarget {
  id: string;
  slug: string;
  title: string | null;
}

function stepExpansion(step: GraphPathStep): Expansion {
  return step.kind === "project"
    ? { id: projectNodeId(step.slug), source: { kind: "project", slug: step.slug } }
    : { id: step.id, source: { kind: "doc", slug: step.slug } };
}

// Module level: a stable `combine` reruns only when a result changes, so the array keeps its identity.
function pickData(results: Array<{ data?: SourceData }>): Array<SourceData | undefined> {
  return results.map((r) => r.data);
}

/**
 * State of one walk through the graph: the tree built from the expansions
 * and their cached data, plus the actions the canvas and the panel call.
 */
export function useExplorer(roots: readonly ExplorerItem[], initial: Expansion[], types: ReadonlySet<RelationType>) {
  const client = useQueryClient();
  const [state, setState] = useState<ExplorerState>(() => initialState(initial));
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [pending, setPending] = useState<ReadonlySet<string>>(NO_PENDING);
  const [error, setError] = useState<string | null>(null);
  /** A walk to a search result is loading. */
  const [walking, setWalking] = useState(false);
  /** A search result no walk from the canvas reaches. */
  const [unreachable, setUnreachable] = useState<WalkTarget | null>(null);

  // Observers keep every expansion's data in the cache while it is on the canvas.
  const datas = useQueries({ queries: state.expansions.map((e) => sourceQuery(e.source)), combine: pickData });
  const loaded = useMemo(() => {
    const map = new Map<string, Loaded>();
    for (const [i, e] of state.expansions.entries()) {
      const data = datas[i];
      if (data) map.set(e.id, toLoaded(data));
    }
    return map;
  }, [state.expansions, datas]);

  const pinned = useMemo(() => new Set(state.pinned), [state.pinned]);
  const tree = useMemo(
    () => buildTree({ roots, expansions: state.expansions, loaded, reveal: state.reveal, pinned, types }),
    [roots, state.expansions, loaded, state.reveal, pinned, types],
  );

  /** The tree of another state, read from the cache (inside updaters). */
  const treeOf = useCallback(
    (s: ExplorerState): ExploredTree => {
      const map = new Map<string, Loaded>();
      for (const e of s.expansions) {
        const data = client.getQueryData<SourceData>(sourceQuery(e.source).queryKey);
        if (data) map.set(e.id, toLoaded(data));
      }
      return buildTree({ roots, expansions: s.expansions, loaded: map, reveal: s.reveal, pinned: new Set(s.pinned), types });
    },
    [client, roots, types],
  );

  const expandNode = useCallback(
    (id: string) => {
      const node = tree.nodes.get(id);
      const source = node ? sourceOf(node.item) : null;
      if (!source || node?.expanded) return;
      setPending((p) => new Set(p).add(id));
      setError(null);
      client
        .fetchQuery(sourceQuery(source))
        .then(
          () =>
            setState((s) => {
              const next = expand(s, { id, source });
              return enforceBudget(touch(next, treeOf(next), id), treeOf, [id, selectedId]).state;
            }),
          (err: unknown) => setError(formatApiError(err)),
        )
        .finally(() =>
          setPending((p) => {
            const next = new Set(p);
            next.delete(id);
            return next;
          }),
        );
    },
    [client, tree, treeOf, selectedId],
  );

  const collapseNode = useCallback(
    (id: string) => setState((s) => ({ ...collapse(s, treeOf(s), id), evicted: 0 })),
    [treeOf],
  );

  /** A click on a card or a list row: select, and open a closed branch. */
  const select = useCallback(
    (id: string | null) => {
      if (id === null) {
        setSelectedId(null);
        return;
      }
      const parent = moreParent(id);
      if (parent !== null) {
        setState((s) => enforceBudget(revealMore(s, parent), treeOf, [parent, selectedId]).state);
        return;
      }
      setSelectedId(id);
      setState((s) => touch(s, treeOf(s), id));
      const node = tree.nodes.get(id);
      if (node && !node.expanded) expandNode(id);
    },
    [tree, treeOf, expandNode, selectedId],
  );

  /**
   * Walks the graph to a search result: asks the server for the shortest
   * path from what is on the canvas, loads every step and opens them in
   * order, so the result appears where it belongs instead of a new start.
   */
  const goTo = useCallback(
    async (target: WalkTarget) => {
      setUnreachable(null);
      setError(null);
      if (tree.nodes.has(target.id)) {
        setSelectedId(target.id);
        setState((s) => touch(s, treeOf(s), target.id));
        return;
      }
      const from: string[] = [];
      const projects: string[] = [];
      for (const n of tree.nodes.values()) {
        if (n.item.kind === "doc" && n.item.expandable) from.push(n.item.id);
        else if (n.item.kind === "project") projects.push(n.item.slug);
      }
      setWalking(true);
      try {
        const { path } = await api.findGraphPath(target.slug, { from, projects, types: [...types] });
        if (!path) {
          setUnreachable(target);
          return;
        }
        const steps = path.slice(0, -1).map(stepExpansion);
        await Promise.all(steps.map((s) => client.fetchQuery(sourceQuery(s.source))));
        setState((s) => {
          const next = walk(s, steps, target.id);
          return enforceBudget(touch(next, treeOf(next), target.id), treeOf, [target.id]).state;
        });
        setSelectedId(target.id);
      } catch (err) {
        setError(formatApiError(err));
      } finally {
        setWalking(false);
      }
    },
    [client, tree, treeOf, types],
  );

  const dismissNotice = useCallback(() => {
    setState((s) => ({ ...s, evicted: 0 }));
    setError(null);
    setUnreachable(null);
  }, []);

  return {
    tree,
    selectedId,
    pending,
    evicted: state.evicted,
    error,
    walking,
    unreachable,
    goTo,
    select,
    expandNode,
    collapseNode,
    dismissNotice,
  };
}
