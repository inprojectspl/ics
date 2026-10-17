/**
 * Card scene of the explored tree: documents as document cards, projects
 * and "more" cards in looks of their own, relations styled by type.
 */
import type { DocType } from "../../api/types";
import { DOC_TYPE_FALLBACK_COLOR } from "../../components/graph/documentStyles";
import { CARD_SIZES, documentCard, relationCardEdge, type CardNode, type CardScene, type Density } from "../../components/graph";
import type { Direction } from "../../components/graph/cardTypes";
import { t, tn } from "../../lib/i18n";
import type { ExploredTree, TreeEdge } from "./explorerTree";
import { layoutTree } from "./treeLayout";

export const PROJECT_COLOR = "#475569";
const MORE_COLOR = DOC_TYPE_FALLBACK_COLOR;

export interface SceneInput {
  tree: ExploredTree;
  density: Density;
  direction: Direction;
  /** Leaves per wrapped line. */
  wrap: number;
  typeLabel: (docType: DocType | null) => string;
  /** Nodes whose expansion is loading. */
  pending: ReadonlySet<string>;
}

function cardOf(input: SceneInput, id: string): CardNode {
  const node = input.tree.nodes.get(id);
  if (!node) return { id, title: id, color: MORE_COLOR, component: 0 };
  const item = node.item;
  if (item.kind === "more") {
    return {
      id,
      title: t("graphExplorer.moreCard", { count: item.hidden }),
      kicker: t("graphExplorer.moreKicker"),
      color: MORE_COLOR,
      variant: "task",
      dashed: true,
      component: 0,
    };
  }
  let state: string | null = null;
  if (input.pending.has(id)) state = t("graphExplorer.stateLoading");
  else if (!node.expanded) state = item.kind === "project" || item.expandable ? t("graphExplorer.stateCollapsed") : t("graphExplorer.stateLeaf");
  if (item.kind === "project") {
    return {
      id,
      title: item.name,
      kicker: [t("graphExplorer.projectKicker"), state].filter(Boolean).join(" · "),
      sub: tn("format.documentCount", item.documents),
      color: PROJECT_COLOR,
      component: 0,
    };
  }
  const card = documentCard(item, 0, input.typeLabel);
  if (state) card.kicker = card.kicker ? `${card.kicker} · ${state}` : state;
  return card;
}

function edgeStyle(e: TreeEdge) {
  if (e.relation) {
    const { id: _id, source: _s, target: _t, ...style } = relationCardEdge(e.relation);
    return style;
  }
  return { kind: "project", color: PROJECT_COLOR, width: 1.2, dashed: true };
}

export function buildScene(input: SceneInput): CardScene {
  return layoutTree(input.tree, {
    size: CARD_SIZES[input.density],
    density: input.density,
    direction: input.direction,
    wrap: input.wrap,
    card: (id) => cardOf(input, id),
    edgeStyle,
  });
}
