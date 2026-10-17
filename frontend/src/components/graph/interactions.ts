/**
 * Pointer, drag and zoom logic for the graph engine, free of DOM and React:
 * callers pass screen coordinates relative to the canvas and own the state.
 */
import { radiusOf } from "./simulation";
import type { SimNode, Size, Transform } from "./types";

export const MIN_ZOOM = 0.2;
export const MAX_ZOOM = 4;

export interface Point {
  x: number;
  y: number;
}

/** Drag or pan in progress between pointer-down and pointer-up. */
export interface PointerState {
  draggingIdx: number | null;
  panning: { startX: number; startY: number; tx: number; ty: number } | null;
}

export function createPointerState(): PointerState {
  return { draggingIdx: null, panning: null };
}

function clampZoom(z: number): number {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z));
}

/** Canvas-relative screen point to world coordinates. */
export function screenToWorld(p: Point, t: Transform): Point {
  return { x: (p.x - t.x) / t.zoom, y: (p.y - t.y) / t.zoom };
}

/** Index of the topmost node under the world point, or null. */
export function hitTest(nodes: SimNode[], world: Point, nodeScale: number): number | null {
  // Iterate from the end: the last drawn nodes (on top) win the hit.
  for (let i = nodes.length - 1; i >= 0; i--) {
    const n = nodes[i];
    if (!n) continue;
    const r = radiusOf(n, nodeScale);
    const dx = world.x - n.x;
    const dy = world.y - n.y;
    if (dx * dx + dy * dy <= r * r) return i;
  }
  return null;
}

/**
 * Pointer-down: a primary press on a node pins it and starts a drag;
 * anything else (empty area, middle button) starts a pan.
 */
export function pointerDown(
  state: PointerState,
  nodes: SimNode[],
  hitIdx: number | null,
  button: number,
  screen: Point,
  t: Transform,
): "drag" | "pan" {
  const node = hitIdx != null ? nodes[hitIdx] : undefined;
  if (node && button === 0) {
    node.pinned = true;
    state.draggingIdx = hitIdx;
    return "drag";
  }
  state.panning = { startX: screen.x, startY: screen.y, tx: t.x, ty: t.y };
  return "pan";
}

/**
 * Pointer-move during a drag or pan. Returns false when neither is active,
 * so the caller should run hover detection instead.
 */
export function pointerMove(
  state: PointerState,
  nodes: SimNode[],
  screen: Point,
  t: Transform,
): boolean {
  if (state.panning) {
    const p = state.panning;
    t.x = p.tx + (screen.x - p.startX);
    t.y = p.ty + (screen.y - p.startY);
    return true;
  }
  if (state.draggingIdx != null) {
    const n = nodes[state.draggingIdx];
    if (n) {
      const w = screenToWorld(screen, t);
      n.x = w.x;
      n.y = w.y;
      n.vx = 0;
      n.vy = 0;
    }
    return true;
  }
  return false;
}

/** Pointer-up: releases the pin so physics resumes, ends any pan. */
export function pointerUp(state: PointerState, nodes: SimNode[]): void {
  if (state.draggingIdx != null) {
    const n = nodes[state.draggingIdx];
    if (n) n.pinned = false;
    state.draggingIdx = null;
  }
  state.panning = null;
}

/** Zooms by `factor` keeping the world point under `anchor` fixed. Mutates `t`. */
export function zoomAround(t: Transform, anchor: Point, factor: number): void {
  const w = screenToWorld(anchor, t);
  const newZoom = clampZoom(t.zoom * factor);
  t.x = anchor.x - w.x * newZoom;
  t.y = anchor.y - w.y * newZoom;
  t.zoom = newZoom;
}

/** Wheel delta to zoom factor. */
export function wheelZoomFactor(deltaY: number): number {
  return Math.exp(-deltaY * 0.0015);
}

/**
 * Transform that centres the nodes' bounding box, so a pan-lost user can
 * find the graph again with one click.
 */
export function fitTransform(nodes: SimNode[], size: Size): Transform {
  if (nodes.length === 0) return { x: 0, y: 0, zoom: 1 };
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const n of nodes) {
    if (n.x < minX) minX = n.x;
    if (n.x > maxX) maxX = n.x;
    if (n.y < minY) minY = n.y;
    if (n.y > maxY) maxY = n.y;
  }
  const bw = maxX - minX || 1;
  const bh = maxY - minY || 1;
  const { w, h } = size;
  // 0.85 pads the view so labels at the edges fit.
  const zoom = clampZoom(Math.min(w / bw, h / bh) * 0.85);
  const cx = (minX + maxX) / 2;
  const cy = (minY + maxY) / 2;
  return { x: w / 2 - cx * zoom, y: h / 2 - cy * zoom, zoom };
}
