/** Overview of the whole card scene with the visible area outlined. */
import type { Point } from "./interactions";
import type { CardScene } from "./cardTypes";
import type { Palette } from "./render";
import type { Size, Transform } from "./types";

export const MINIMAP_SIZE: Size = { w: 196, h: 124 };
const INSET = 8;

interface Mapping {
  scale: number;
  ox: number;
  oy: number;
}

function mapping(scene: Pick<CardScene, "width" | "height">, box: Size): Mapping {
  const scale = Math.min((box.w - INSET * 2) / Math.max(1, scene.width), (box.h - INSET * 2) / Math.max(1, scene.height));
  return { scale, ox: (box.w - scene.width * scale) / 2, oy: (box.h - scene.height * scale) / 2 };
}

/** Minimap point to the world point it shows. */
export function minimapToWorld(scene: Pick<CardScene, "width" | "height">, p: Point, box: Size = MINIMAP_SIZE): Point {
  const m = mapping(scene, box);
  return { x: (p.x - m.ox) / m.scale, y: (p.y - m.oy) / m.scale };
}

/** Whether the view already shows the whole scene, so the overview adds nothing. */
export function wholeSceneInView(scene: Pick<CardScene, "width" | "height">, view: Transform, viewSize: Size): boolean {
  const vx = -view.x / view.zoom;
  const vy = -view.y / view.zoom;
  return vx <= 0 && vy <= 0 && vx + viewSize.w / view.zoom >= scene.width && vy + viewSize.h / view.zoom >= scene.height;
}

// Frames and cards do not move while the view does: they are drawn once per
// scene and theme into an offscreen canvas, and each frame only copies it.
const layers = new WeakMap<CardScene, { palette: Palette; canvas: HTMLCanvasElement }>();

function staticLayer(scene: CardScene, palette: Palette, box: Size): HTMLCanvasElement | null {
  const hit = layers.get(scene);
  if (hit && hit.palette === palette) return hit.canvas;
  const dpr = window.devicePixelRatio || 1;
  const canvas = document.createElement("canvas");
  canvas.width = box.w * dpr;
  canvas.height = box.h * dpr;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  const m = mapping(scene, box);
  ctx.scale(dpr, dpr);
  ctx.translate(m.ox, m.oy);
  ctx.scale(m.scale, m.scale);
  ctx.lineWidth = 1 / m.scale;
  ctx.strokeStyle = palette.rule;
  for (const f of scene.frames) ctx.strokeRect(f.x, f.y, f.w, f.h);
  for (const c of scene.cards) {
    ctx.globalAlpha = c.muted ? 0.4 : 0.9;
    ctx.fillStyle = c.variant === "task" ? palette.inkMute : c.color;
    ctx.fillRect(c.x, c.y, c.w, c.h);
  }
  layers.set(scene, { palette, canvas });
  return canvas;
}

export function drawMinimap(
  canvas: HTMLCanvasElement,
  scene: CardScene,
  view: Transform,
  viewSize: Size,
  palette: Palette,
  box: Size = MINIMAP_SIZE,
): void {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.clearRect(0, 0, box.w, box.h);
  const layer = staticLayer(scene, palette, box);
  if (layer) ctx.drawImage(layer, 0, 0, box.w, box.h);
  // The outline stays inside the overview even when the view reaches past the scene.
  const vx = -view.x / view.zoom;
  const vy = -view.y / view.zoom;
  const x = Math.max(vx, 0);
  const y = Math.max(vy, 0);
  const w = Math.min(vx + viewSize.w / view.zoom, scene.width) - x;
  const h = Math.min(vy + viewSize.h / view.zoom, scene.height) - y;
  if (w <= 0 || h <= 0) return;
  const m = mapping(scene, box);
  ctx.save();
  ctx.translate(m.ox, m.oy);
  ctx.scale(m.scale, m.scale);
  ctx.fillStyle = palette.accent;
  ctx.globalAlpha = 0.1;
  ctx.fillRect(x, y, w, h);
  ctx.globalAlpha = 1;
  ctx.strokeStyle = palette.accent;
  ctx.lineWidth = 1.5 / m.scale;
  ctx.strokeRect(x, y, w, h);
  ctx.restore();
}
