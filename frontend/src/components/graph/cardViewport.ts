/**
 * Viewport maths of the card canvas, free of DOM and React: fitting the
 * scene, zooming around a point and easing between two views.
 */
import type { Point } from "./interactions";
import type { CardScene } from "./cardTypes";
import type { Size, Transform } from "./types";

export interface ZoomRange {
  min: number;
  max: number;
}

export const CARD_ZOOM: ZoomRange = { min: 0.04, max: 2.5 };

export function clampZoom(zoom: number, range: ZoomRange = CARD_ZOOM): number {
  return Math.min(range.max, Math.max(range.min, zoom));
}

/** A fit never enlarges past 100%: a few cards would otherwise fill the canvas. */
export const FIT_MAX_ZOOM = 1;
/** Screen padding a fit keeps around the scene by default. */
export const FIT_PAD = 32;
/** Height of the toolbar strip an interactive canvas keeps free below the scene. */
export const TOOLBAR_INSET = 44;

/**
 * View that shows the whole scene centred, with `pad` screen pixels around
 * it and `bottom` more below (room for controls drawn over the canvas),
 * no closer than `FIT_MAX_ZOOM`.
 */
export function fitScene(
  scene: Pick<CardScene, "width" | "height">,
  size: Size,
  pad = 32,
  range: ZoomRange = CARD_ZOOM,
  bottom = 0,
): Transform {
  if (scene.width <= 0 || scene.height <= 0 || size.w <= 0 || size.h <= 0) return { x: 0, y: 0, zoom: 1 };
  const room = { w: size.w - pad * 2, h: size.h - pad * 2 - bottom };
  const zoom = clampZoom(Math.min(room.w / scene.width, room.h / scene.height), {
    min: range.min,
    max: Math.min(range.max, FIT_MAX_ZOOM),
  });
  return { x: (size.w - scene.width * zoom) / 2, y: pad + (room.h - scene.height * zoom) / 2, zoom };
}

/** Zoom below which a focused neighbourhood is not shrunk further: titles stay readable. */
export const FOCUS_MIN_ZOOM = 0.8;

type Box = { x: number; y: number; w: number; h: number };

/**
 * View that frames the given cards (a selection and its neighbours), no
 * closer than a fit allows, since a lone card should not fill the screen, and no
 * further than `FOCUS_MIN_ZOOM`: a wide fan is centred on `centre` and the
 * rest is a pan away.
 */
export function fitCards(
  cards: ReadonlyArray<Box>,
  size: Size,
  pad = 32,
  range: ZoomRange = CARD_ZOOM,
  bottom = 0,
  centre?: Box,
): Transform | null {
  if (cards.length === 0) return null;
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const c of cards) {
    minX = Math.min(minX, c.x);
    minY = Math.min(minY, c.y);
    maxX = Math.max(maxX, c.x + c.w);
    maxY = Math.max(maxY, c.y + c.h);
  }
  const t = fitScene({ width: maxX - minX, height: maxY - minY }, size, pad, range, bottom);
  if (t.zoom < FOCUS_MIN_ZOOM && centre) {
    const zoom = Math.max(FOCUS_MIN_ZOOM, range.min);
    return {
      x: size.w / 2 - (centre.x + centre.w / 2) * zoom,
      y: (size.h - bottom) / 2 - (centre.y + centre.h / 2) * zoom,
      zoom,
    };
  }
  return { x: t.x - minX * t.zoom, y: t.y - minY * t.zoom, zoom: t.zoom };
}

/** `t` zoomed by `factor` keeping the world point under `anchor` in place. */
export function zoomAt(t: Transform, anchor: Point, factor: number, range: ZoomRange = CARD_ZOOM): Transform {
  const zoom = clampZoom(t.zoom * factor, range);
  const wx = (anchor.x - t.x) / t.zoom;
  const wy = (anchor.y - t.y) / t.zoom;
  return { x: anchor.x - wx * zoom, y: anchor.y - wy * zoom, zoom };
}

/** View centred on a world point at the current zoom. */
export function centreOn(t: Transform, world: Point, size: Size): Transform {
  return { x: size.w / 2 - world.x * t.zoom, y: size.h / 2 - world.y * t.zoom, zoom: t.zoom };
}

/**
 * Wheel event to a zoom factor. A pinch arrives with `ctrlKey` and gets a
 * steeper curve; a line-based wheel is scaled to pixels first.
 */
export function wheelFactor(e: { deltaY: number; deltaMode: number; ctrlKey: boolean }): number {
  const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 800 : 1;
  const f = Math.exp(-e.deltaY * unit * (e.ctrlKey ? 0.01 : 0.0022));
  return Math.min(1.6, Math.max(1 / 1.6, f));
}

const easeOut = (x: number): number => 1 - Math.pow(1 - x, 3);

/**
 * Point `progress` (0..1) of the way from `a` to `b`. Zoom is interpolated
 * in log space and the pan follows the world point at the screen centre, so
 * the motion reads as one smooth dolly instead of a slide plus a zoom.
 */
export function blendTransform(a: Transform, b: Transform, progress: number, size: Size): Transform {
  const k = easeOut(Math.min(1, Math.max(0, progress)));
  const zoom = Math.exp(Math.log(a.zoom) + (Math.log(b.zoom) - Math.log(a.zoom)) * k);
  const ca = { x: (size.w / 2 - a.x) / a.zoom, y: (size.h / 2 - a.y) / a.zoom };
  const cb = { x: (size.w / 2 - b.x) / b.zoom, y: (size.h / 2 - b.y) / b.zoom };
  const c = { x: ca.x + (cb.x - ca.x) * k, y: ca.y + (cb.y - ca.y) * k };
  return { x: size.w / 2 - c.x * zoom, y: size.h / 2 - c.y * zoom, zoom };
}
