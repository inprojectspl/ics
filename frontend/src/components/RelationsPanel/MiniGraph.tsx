import { useCallback, useMemo, useRef } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "../../api";
import { RELATION_TYPES } from "../../api/relationTypes";
import { formatApiError } from "../../lib/apiError";
import { t, tn } from "../../lib/i18n";
import { navigate } from "../../lib/navigate";
import { openInNewTab } from "../../lib/newTab";
import { qk } from "../../lib/queries";
import { useDocTypeLabel } from "../../lib/useDocTypes";
import { CardCanvas, LAYER_RELATIONS, layoutCardScene, useElementSize } from "../graph";
import { GraphLegend } from "./GraphLegend";
import { toMiniGraph } from "./miniGraphData";

interface Props {
  slug: string;
}

const PAD = 12;
const GAP = 10;
const CARD_H = 46;
const MIN_CARD_W = 200;
const MAX_CARD_W = 264;
// Below this the titles stop being readable: the panel scrolls instead.
const ZOOM = { min: 0.75, max: 1 };

/**
 * The document's direct neighbours as cards on the shared engine; a click
 * opens a card. Deeper walks belong to the full graph view, where there is
 * room to pan and zoom.
 */
export function MiniGraph({ slug }: Props) {
  const { data, error } = useQuery({
    queryKey: qk.neighbourhood(slug, 1),
    // Every type, as the relation list next to it shows: the default would
    // leave out content links and draw a document linked only by them alone.
    queryFn: () => api.getNeighbourhood(slug, { depth: 1, types: RELATION_TYPES }),
  });
  const typeLabel = useDocTypeLabel();
  const graph = useMemo(() => (data ? toMiniGraph(data, typeLabel) : null), [data, typeLabel]);

  const wrapRef = useRef<HTMLDivElement | null>(null);
  const width = Math.round(useElementSize(wrapRef).w);
  const room = Math.max(160, (width || 280) - PAD * 2);

  // Cards take the panel width: one per row in a narrow panel, more when it is wide.
  const scene = useMemo(() => {
    if (!graph) return null;
    const perRow = Math.max(1, Math.floor((room + GAP) / (MIN_CARD_W + GAP)));
    const cardW = Math.min(MAX_CARD_W, (room - (perRow - 1) * GAP) / perRow);
    return layoutCardScene(graph.cards, graph.edges, {
      size: { w: cardW, h: CARD_H },
      density: "compact",
      layerKinds: LAYER_RELATIONS,
      frames: false,
      maxPerRow: perRow,
      gapX: GAP,
      gapY: 30,
      // Tall rather than wide: the panel grows downwards and scrolls.
      aspect: 0.2,
    });
  }, [graph, room]);
  // The box follows the scene at the zoom the fit will pick, so no band stays empty.
  const zoom = scene ? Math.min(ZOOM.max, Math.max(ZOOM.min, room / Math.max(1, scene.width))) : 1;
  const height = scene ? Math.max(120, Math.ceil(scene.height * zoom) + PAD * 2) : 160;

  const onSelect = useCallback(
    (id: string | null) => {
      const target = id ? graph?.slugs.get(id) : undefined;
      if (target && target !== slug) navigate(`/v/${target}`);
    },
    [graph, slug],
  );

  const onOpenNewTab = useCallback(
    (id: string) => {
      const target = graph?.slugs.get(id);
      if (target) openInNewTab(`/v/${target}`);
    },
    [graph],
  );

  const label = graph
    ? `${t("miniGraph.label")}: ${tn("miniGraph.nodes", graph.cards.length)}, ${tn("miniGraph.edges", graph.edges.length)}`
    : t("miniGraph.label");

  return (
    <div>
      {error && <p className="text-meta text-danger">{formatApiError(error)}</p>}
      {data?.truncated && <p className="text-meta text-text-tertiary mb-1">{t("miniGraph.truncated")}</p>}
      <div ref={wrapRef} className="rounded-control border border-border bg-surface overflow-hidden" style={{ height }}>
        {scene && (
          <CardCanvas
            scene={scene}
            selectedId={data?.root_id ?? null}
            onSelect={onSelect}
            onOpenNewTab={onOpenNewTab}
            label={label}
            interactive={false}
            focusSelection={false}
            fitPadding={PAD}
            zoomRange={ZOOM}
          />
        )}
      </div>
      {graph && <GraphLegend cards={graph.cards} edges={graph.edges} />}
    </div>
  );
}
