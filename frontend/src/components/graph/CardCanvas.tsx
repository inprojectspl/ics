import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { clsx } from "clsx";

import { formatNumber, t } from "../../lib/i18n";
import { useMediaQuery } from "../../lib/useMediaQuery";
import { buttonClass } from "../ui/Button";
import { sizeCanvas, toScreen, useCanvasSize, useFrame, usePalette, useRenderLoop } from "./canvas";
import { drawCardScene, focusOf, hitCard, type Focus } from "./cardRender";
import type { CardScene } from "./cardTypes";
import {
  blendTransform,
  CARD_ZOOM,
  centreOn,
  FIT_PAD,
  fitCards,
  fitScene,
  TOOLBAR_INSET,
  wheelFactor,
  zoomAt,
  type ZoomRange,
} from "./cardViewport";
import { screenToWorld, type Point } from "./interactions";
import { drawMinimap, MINIMAP_SIZE, minimapToWorld, wholeSceneInView } from "./minimap";
import type { Size, Transform } from "./types";

interface Props {
  scene: CardScene;
  selectedId: string | null;
  /** A click on a card; null for a click on empty canvas. */
  onSelect: (id: string | null) => void;
  /** Ctrl/Cmd+click or a middle click on a card: open it in a new tab instead of selecting it. */
  onOpenNewTab?: (id: string) => void;
  /** Accessible name of the canvas. */
  label: string;
  /** Pan, wheel zoom, toolbar and minimap; off for a static preview. */
  interactive?: boolean;
  /** Light the selected card's neighbourhood and label its edges; hover always does. */
  focusSelection?: boolean;
  /** Screen padding kept around the scene by a fit. */
  fitPadding?: number;
  zoomRange?: ZoomRange;
  /** Screen width on the right covered by a panel over the canvas; a fit centres the scene beside it. */
  fitInsetRight?: number;
  /** Extra controls placed after the zoom buttons. */
  toolbarExtra?: ReactNode;
  className?: string;
}

// A press that moves less than this is a click, not a pan.
const CLICK_SLOP = 4;
const TWEEN_MS = 280;
const STEP = 1.25;
/** Narrower than this, the minimap would cover the toolbar. */
const MINIMAP_FROM_WIDTH = 880;

/** The part of the canvas not covered by a panel on its right. */
function visible(size: Size, right: number): Size {
  return { w: Math.max(1, size.w - right), h: size.h };
}

/**
 * Canvas of a card scene on the shared engine: draws only when something
 * changed, pans with a drag, zooms with the wheel around the cursor, eases
 * between views, and lights the neighbourhood of the hovered card.
 */
export function CardCanvas(props: Props) {
  const { scene, selectedId, onSelect, label, interactive = true, focusSelection = true } = props;
  const range = props.zoomRange ?? CARD_ZOOM;
  const pad = props.fitPadding ?? FIT_PAD;
  // The toolbar sits over the bottom edge, so a fit keeps that strip free.
  const inset = interactive ? TOOLBAR_INSET : 0;
  const right = props.fitInsetRight ?? 0;
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const transform = useRef<Transform>({ x: 0, y: 0, zoom: 1 });
  const tween = useRef<{ from: Transform; to: Transform; start: number } | null>(null);
  const hover = useRef<string | null>(null);
  const focus = useRef<Focus | null>(null);
  const press = useRef<{ start: Point; origin: Transform; moved: boolean } | null>(null);
  const userMoved = useRef(false);
  const sceneRef = useRef(scene);
  const selectedRef = useRef(selectedId);
  const zoomRef = useRef<HTMLSpanElement | null>(null);
  const reduceMotion = useMediaQuery("(prefers-reduced-motion: reduce)");
  const [cursor, setCursor] = useState<"grab" | "pointer" | "grabbing">("grab");
  const miniRef = useRef<HTMLCanvasElement | null>(null);
  const miniDrag = useRef(false);
  const showMinimap = interactive && scene.cards.length > 12;

  const loop = useRenderLoop();
  const { invalidate } = loop;
  const palette = usePalette(invalidate);

  const refocus = useCallback(() => {
    focus.current = focusOf(sceneRef.current, hover.current ?? (focusSelection ? selectedRef.current : null));
  }, [focusSelection]);

  /** Moves the view, eased unless the user prefers reduced motion. */
  const moveTo = useCallback(
    (to: Transform, animate: boolean) => {
      if (animate && !reduceMotion) {
        tween.current = { from: { ...transform.current }, to, start: performance.now() };
      } else {
        tween.current = null;
        transform.current = to;
      }
      invalidate();
    },
    [invalidate, reduceMotion],
  );

  /** The view a fit goes to: the selection's neighbourhood, or the whole scene. */
  const fitView = useCallback(
    (full: Size): Transform => {
      const s = visible(full, right);
      const focused = interactive && focusSelection ? focusOf(sceneRef.current, selectedRef.current) : null;
      const cards = focused ? sceneRef.current.cards.filter((c) => focused.cards.has(c.id)) : [];
      const centre = cards.find((c) => c.id === focused?.centre);
      return fitCards(cards, s, pad + 24, range, inset, centre) ?? fitScene(sceneRef.current, s, pad, range, inset);
    },
    [interactive, focusSelection, pad, range, inset, right],
  );

  const size = useCanvasSize(wrapRef, canvasRef, { w: 800, h: 560 }, (s) => {
    if (!userMoved.current) {
      tween.current = null;
      transform.current = fitView(s);
    }
    invalidate();
  });

  useFrame(loop, () => {
    const tw = tween.current;
    let more = false;
    if (tw) {
      const progress = (performance.now() - tw.start) / TWEEN_MS;
      transform.current = blendTransform(tw.from, tw.to, progress, size.current);
      if (progress >= 1) tween.current = null;
      else more = true;
    }
    const canvas = canvasRef.current;
    if (canvas) {
      drawCardScene({
        canvas,
        scene: sceneRef.current,
        size: size.current,
        transform: transform.current,
        palette: palette.current,
        hoverId: hover.current,
        selectedId: selectedRef.current,
        focus: focus.current,
        grid: interactive,
      });
    }
    const mini = miniRef.current;
    if (mini) {
      const shown = size.current.w - right >= MINIMAP_FROM_WIDTH && !wholeSceneInView(sceneRef.current, transform.current, size.current);
      mini.style.visibility = shown ? "visible" : "hidden";
      if (shown) drawMinimap(mini, sceneRef.current, transform.current, size.current, palette.current);
    }
    // Written to the DOM directly: a React render per animation frame would redo the toolbar.
    const level = zoomRef.current;
    if (level) {
      const pct = formatNumber(Math.round(transform.current.zoom * 100));
      level.textContent = `${pct}%`;
      level.setAttribute("aria-label", t("cardGraph.zoomLevel", { value: pct }));
    }
    return more;
  });

  useEffect(() => {
    selectedRef.current = selectedId;
    refocus();
    invalidate();
    // A selection (on the canvas or from a list) frames its neighbourhood.
    if (!selectedId || !interactive || !focusSelection) return;
    if (!sceneRef.current.cards.some((c) => c.id === selectedId)) return;
    userMoved.current = false;
    moveTo(fitView(size.current), true);
  }, [selectedId, refocus, invalidate, interactive, focusSelection, moveTo, size, fitView]);

  // A new scene (data, filters, density, mode) is shown whole.
  useEffect(() => {
    const had = sceneRef.current.cards.length > 0 && sceneRef.current !== scene;
    sceneRef.current = scene;
    hover.current = null;
    userMoved.current = false;
    refocus();
    moveTo(fitView(size.current), had);
  }, [scene, refocus, moveTo, size, fitView]);

  useEffect(() => {
    const mini = miniRef.current;
    if (!mini) return;
    sizeCanvas(mini, MINIMAP_SIZE);
    invalidate();
  }, [showMinimap, invalidate]);

  // A non-passive listener: the wheel zooms the canvas instead of scrolling the page.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !interactive) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      userMoved.current = true;
      tween.current = null;
      transform.current = zoomAt(transform.current, toScreen(canvas, e), wheelFactor(e), range);
      invalidate();
    };
    canvas.addEventListener("wheel", onWheel, { passive: false });
    return () => canvas.removeEventListener("wheel", onWheel);
  }, [interactive, invalidate, range]);

  const world = (p: Point): Point => screenToWorld(p, transform.current);

  const setHover = (id: string | null) => {
    if (id === hover.current) return;
    hover.current = id;
    refocus();
    setCursor(id ? "pointer" : "grab");
    invalidate();
  };

  const onPointerDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    // The middle button opens a card in a new tab (`auxclick`); it never pans.
    if (e.button === 1) return;
    const p = toScreen(canvasRef.current, e);
    press.current = { start: p, origin: { ...transform.current }, moved: false };
    if (interactive) e.currentTarget.setPointerCapture(e.pointerId);
  };

  const onPointerMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const p = toScreen(canvasRef.current, e);
    const pr = press.current;
    if (pr && interactive) {
      const dx = p.x - pr.start.x;
      const dy = p.y - pr.start.y;
      if (pr.moved || Math.hypot(dx, dy) >= CLICK_SLOP) {
        pr.moved = true;
        userMoved.current = true;
        tween.current = null;
        transform.current = { ...pr.origin, x: pr.origin.x + dx, y: pr.origin.y + dy };
        setCursor("grabbing");
        invalidate();
        return;
      }
    }
    setHover(hitCard(sceneRef.current, world(p))?.id ?? null);
  };

  const onPointerUp = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const pr = press.current;
    press.current = null;
    if (!pr || pr.moved) {
      setCursor(hover.current ? "pointer" : "grab");
      return;
    }
    const card = hitCard(sceneRef.current, world(toScreen(canvasRef.current, e)));
    if (card && props.onOpenNewTab && (e.ctrlKey || e.metaKey)) {
      props.onOpenNewTab(card.id);
      return;
    }
    onSelect(card?.id ?? null);
  };

  const zoomBy = (factor: number) => {
    const s = visible(size.current, right);
    userMoved.current = true;
    moveTo(zoomAt(tween.current?.to ?? transform.current, { x: s.w / 2, y: s.h / 2 }, factor, range), true);
  };
  const centreFromMinimap = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const p = minimapToWorld(sceneRef.current, toScreen(e.currentTarget, e));
    userMoved.current = true;
    moveTo(centreOn(transform.current, p, size.current), false);
  };
  const fit = () => {
    userMoved.current = false;
    moveTo(fitScene(sceneRef.current, visible(size.current, right), pad, range, inset), true);
  };

  const button = clsx(buttonClass("secondary", "sm"), "min-w-9 px-3");

  return (
    <div ref={wrapRef} className={clsx("relative h-full w-full overflow-hidden", props.className)}>
      <canvas
        ref={canvasRef}
        role="img"
        aria-label={label}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        // Without this the browser starts autoscroll on a middle press.
        onMouseDown={(e) => {
          if (e.button === 1 && props.onOpenNewTab) e.preventDefault();
        }}
        onAuxClick={(e) => {
          if (e.button !== 1 || !props.onOpenNewTab) return;
          const card = hitCard(sceneRef.current, world(toScreen(canvasRef.current, e)));
          if (card) props.onOpenNewTab(card.id);
        }}
        onPointerCancel={() => {
          press.current = null;
        }}
        onPointerLeave={() => {
          if (!press.current) setHover(null);
        }}
        style={{ cursor: interactive ? cursor : cursor === "pointer" ? "pointer" : "default" }}
        className="block touch-none select-none"
      />
      {interactive && (
        <>
          <div className="absolute bottom-3 left-3 max-w-[calc(100%-1.5rem)] flex flex-wrap items-center gap-1.5 rounded-card border border-border bg-surface/90 p-1.5 shadow-card backdrop-blur-sm">
            <button type="button" className={button} onClick={fit} title={t("cardGraph.fitTitle")}>
              {t("cardGraph.fit")}
            </button>
            <button type="button" className={button} onClick={() => zoomBy(STEP)} aria-label={t("cardGraph.zoomIn")}>
              +
            </button>
            <button type="button" className={button} onClick={() => zoomBy(1 / STEP)} aria-label={t("cardGraph.zoomOut")}>
              −
            </button>
            <span ref={zoomRef} className="px-1.5 text-meta tabular-nums text-text-tertiary" />
            {props.toolbarExtra}
          </div>
          {showMinimap && (
            <canvas
              ref={miniRef}
              aria-hidden
              onPointerDown={(e) => {
                miniDrag.current = true;
                e.currentTarget.setPointerCapture(e.pointerId);
                centreFromMinimap(e);
              }}
              onPointerMove={(e) => {
                if (miniDrag.current) centreFromMinimap(e);
              }}
              onPointerUp={() => {
                miniDrag.current = false;
              }}
              // Beside a panel covering the right of the canvas, not under it.
              style={{ right: 12 + right }}
              className="absolute bottom-3 hidden sm:block rounded-control border border-border bg-surface/95 shadow-card cursor-crosshair touch-none"
            />
          )}
        </>
      )}
    </div>
  );
}
