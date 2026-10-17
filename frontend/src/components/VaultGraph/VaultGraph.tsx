import { useCallback, useEffect, useRef, useState } from "react";

import { formatApiError } from "../../lib/apiError";
import { t, tn } from "../../lib/i18n";
import { HoverPanel } from "./HoverPanel";
import { SettingsPanel } from "./SettingsPanel";
import { Toolbar } from "./Toolbar";
import { DEFAULT_SETTINGS, loadSettings, saveSettings } from "./settings";
import {
  buildSimulation,
  createPointerState,
  drawScene,
  fitTransform,
  hitTest as hitTestNodes,
  neighboursOf,
  pointerDown,
  pointerMove,
  pointerUp,
  screenToWorld,
  stepSimulation,
  toScreen,
  useCanvasSize,
  useFrame,
  usePalette,
  useRenderLoop,
  wheelZoomFactor,
  zoomAround as zoomTransform,
} from "../graph";
import type { Point, SimEdge, Transform } from "../graph";
import { toGraph } from "./graphData";
import type { GraphSettings, Props, SimNode } from "./types";

/**
 * Force-directed graph of the vault's wikilinks on a single canvas. Force
 * model, drawing and pointer logic come from the `graph` engine; this
 * component owns the rAF loop, refs and the React chrome.
 */
export function VaultGraph({ source, fetcher, onOpenFile, currentPath }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [counts, setCounts] = useState<{ nodes: number; edges: number }>({ nodes: 0, edges: 0 });
  const [settings, setSettings] = useState<GraphSettings>(() => loadSettings());
  const [showSettings, setShowSettings] = useState(false);

  // Refs mirror props and state for the rAF loop, which runs outside React.
  const settingsRef = useRef(settings);
  useEffect(() => {
    settingsRef.current = settings;
    saveSettings(settings);
  }, [settings]);

  const currentPathRef = useRef(currentPath);
  useEffect(() => {
    currentPathRef.current = currentPath;
  }, [currentPath]);

  const nodesRef = useRef<SimNode[]>([]);
  const edgesRef = useRef<SimEdge[]>([]);
  const transformRef = useRef<Transform>({ x: 0, y: 0, zoom: 1 });
  const hoverIdxRef = useRef<number | null>(null);
  const pointerRef = useRef(createPointerState());

  // The vault graph keeps simulating while mounted: the frame always asks for the next one.
  const loop = useRenderLoop();
  const paletteRef = usePalette(loop.invalidate);
  const sizeRef = useCanvasSize(wrapRef, canvasRef, { w: 800, h: 600 }, loop.invalidate);
  useFrame(loop, () => {
    stepSimulation(nodesRef.current, edgesRef.current, sizeRef.current, settingsRef.current);
    const canvas = canvasRef.current;
    if (canvas) {
      drawScene({
        canvas,
        nodes: nodesRef.current,
        edges: edgesRef.current,
        size: sizeRef.current,
        transform: transformRef.current,
        settings: settingsRef.current,
        hoverIdx: hoverIdxRef.current,
        currentId: currentPathRef.current,
        palette: paletteRef.current,
      });
    }
    return true;
  });

  const [hoverInfo, setHoverInfo] = useState<{
    node: SimNode;
    neighbours: SimNode[];
  } | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetcher()
      .then((g) => {
        if (cancelled) return;
        const graph = toGraph(g);
        const { nodes, edges } = buildSimulation(graph.nodes, graph.edges, sizeRef.current);
        nodesRef.current = nodes;
        edgesRef.current = edges;
        transformRef.current = { x: 0, y: 0, zoom: 1 };
        setCounts({ nodes: nodes.length, edges: edges.length });
        setLoading(false);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(formatApiError(e));
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // Refetch only when the graph source changes; the loader closure is
    // recreated every render and would refetch on each one.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source]);

  const hitTest = useCallback(
    (screen: Point): number | null =>
      hitTestNodes(
        nodesRef.current,
        screenToWorld(screen, transformRef.current),
        settingsRef.current.nodeScale,
      ),
    [],
  );

  const onPointerMove = useCallback(
    (e: React.PointerEvent) => {
      const screen = toScreen(canvasRef.current, e);
      if (pointerMove(pointerRef.current, nodesRef.current, screen, transformRef.current)) return;
      const idx = hitTest(screen);
      hoverIdxRef.current = idx;
      const node = idx != null ? nodesRef.current[idx] : null;
      if (!node || idx == null) {
        // `idx != null && node == null` is a race with a list mutation; clear
        // the hover so the tooltip does not stick to a stale node.
        setHoverInfo(null);
        return;
      }
      const nbr = neighboursOf(idx, edgesRef.current, nodesRef.current);
      setHoverInfo({ node, neighbours: nbr });
    },
    [hitTest],
  );

  const onPointerDown = useCallback(
    (e: React.PointerEvent) => {
      const screen = toScreen(canvasRef.current, e);
      pointerDown(
        pointerRef.current,
        nodesRef.current,
        hitTest(screen),
        e.button,
        screen,
        transformRef.current,
      );
      (e.target as Element).setPointerCapture(e.pointerId);
    },
    [hitTest],
  );

  const onPointerUp = useCallback((e: React.PointerEvent) => {
    // A click never opens the file: a nudged drag would. Opening is a double-click.
    pointerUp(pointerRef.current, nodesRef.current);
    try { (e.target as Element).releasePointerCapture(e.pointerId); } catch { /* ignore */ }
  }, []);

  const onDoubleClick = useCallback(
    (e: React.MouseEvent) => {
      const idx = hitTest(toScreen(canvasRef.current, e));
      const node = idx != null ? nodesRef.current[idx] : null;
      if (!node) return;
      e.preventDefault();
      onOpenFile(node.path);
    },
    [hitTest, onOpenFile],
  );

  const zoomAround = useCallback((clientX: number, clientY: number, factor: number) => {
    if (!canvasRef.current) return;
    zoomTransform(transformRef.current, toScreen(canvasRef.current, { clientX, clientY }), factor);
  }, []);

  const onWheel = useCallback(
    (e: React.WheelEvent) => {
      e.preventDefault();
      zoomAround(e.clientX, e.clientY, wheelZoomFactor(e.deltaY));
    },
    [zoomAround],
  );

  const zoomBy = useCallback((factor: number) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const r = canvas.getBoundingClientRect();
    zoomAround(r.left + r.width / 2, r.top + r.height / 2, factor);
  }, [zoomAround]);

  const resetView = useCallback(() => {
    transformRef.current = fitTransform(nodesRef.current, sizeRef.current);
  }, [sizeRef]);

  return (
    <div
      ref={wrapRef}
      className="relative w-full h-[calc(100vh-7rem)] rounded-control border border-border bg-surface/60 overflow-hidden"
    >
      <canvas
        ref={canvasRef}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onDoubleClick={onDoubleClick}
        onWheel={onWheel}
        className="block cursor-grab active:cursor-grabbing"
      />
      <div className="absolute top-3 left-3 text-meta text-text-tertiary bg-surface/90 backdrop-blur-sm rounded-full px-3 py-1 border border-border">
        <span className="font-code tabular-nums text-text-secondary">{counts.nodes}</span>{" "}
        {tn("vaultGraph.notes", counts.nodes)} ·{" "}
        <span className="font-code tabular-nums text-text-secondary">{counts.edges}</span>{" "}
        {tn("vaultGraph.links", counts.edges)}
        <span className="hidden md:inline">
          {" · "}
          <span className="text-text-tertiary">{t("vaultGraph.doubleClickHint")}</span>
        </span>
      </div>
      <Toolbar
        onZoomIn={() => zoomBy(1.25)}
        onZoomOut={() => zoomBy(0.8)}
        onFit={resetView}
        onToggleSettings={() => setShowSettings((s) => !s)}
        settingsOpen={showSettings}
      />
      {showSettings && (
        <SettingsPanel
          settings={settings}
          onChange={setSettings}
          onReset={() => setSettings(DEFAULT_SETTINGS)}
          onClose={() => setShowSettings(false)}
        />
      )}
      {hoverInfo && (
        <HoverPanel info={hoverInfo} onOpen={() => onOpenFile(hoverInfo.node.path)} />
      )}
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center text-text-tertiary text-ui">
          {t("vaultGraph.loading")}
        </div>
      )}
      {error && (
        <div className="absolute inset-0 flex items-center justify-center text-danger text-ui">
          {error}
        </div>
      )}
      {!loading && !error && counts.nodes === 0 && (
        <div className="absolute inset-0 flex items-center justify-center text-text-tertiary text-ui text-center px-6">
          {t("vaultGraph.empty")}
        </div>
      )}
      {!loading && !error && counts.nodes > 0 && counts.edges === 0 && (
        <div className="absolute bottom-3 left-3 right-3 text-center text-meta text-text-tertiary">
          {t("vaultGraph.noLinksBefore")}{" "}
          <code className="font-code">{t("vaultGraph.noLinksExample")}</code>{" "}
          {t("vaultGraph.noLinksAfter")}
        </div>
      )}
    </div>
  );
}
