import { useEffect, useRef } from "react";
import { prefersReducedMotion } from "../../lib/motion";
import { usePalette, type Palette } from "../graph";
import { linkStrength, scaleNodes, seedNodes, stepNodes, type DriftNode } from "./drift";

/** Link opacity steps: one path and one stroke per step, whatever the node count. */
const LINK_LEVELS = 5;
const BRAND_RADIUS = 2.6;

function draw(ctx: CanvasRenderingContext2D, nodes: DriftNode[], w: number, h: number, p: Palette): void {
  ctx.clearRect(0, 0, w, h);
  const maxDist = Math.min(w, h) * 0.18;
  const linkAlpha = p.dark ? 0.24 : 0.28;

  // 36 nodes make about 630 pairs; each link joins the path of its
  // strength step, so a frame costs LINK_LEVELS strokes, not one per link.
  const levels: DriftNode[][] = Array.from({ length: LINK_LEVELS }, () => []);
  for (let i = 0; i < nodes.length; i++) {
    const a = nodes[i];
    if (!a) continue;
    for (let j = i + 1; j < nodes.length; j++) {
      const b = nodes[j];
      if (!b) continue;
      const s = linkStrength(a, b, maxDist);
      if (s === 0) continue;
      levels[Math.min(LINK_LEVELS - 1, Math.floor(s * LINK_LEVELS))]?.push(a, b);
    }
  }
  ctx.lineWidth = 0.6;
  ctx.strokeStyle = p.inkMute;
  levels.forEach((pairs, level) => {
    if (pairs.length === 0) return;
    ctx.globalAlpha = (linkAlpha * (level + 1)) / LINK_LEVELS;
    ctx.beginPath();
    for (let k = 0; k + 1 < pairs.length; k += 2) {
      const a = pairs[k];
      const b = pairs[k + 1];
      if (!a || !b) continue;
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
    }
    ctx.stroke();
  });

  // Brand nodes are the only saturated colour on the screen; keep them quiet.
  for (const brand of [false, true]) {
    ctx.fillStyle = brand ? p.brand : p.inkMute;
    ctx.globalAlpha = brand ? 0.7 : p.dark ? 0.5 : 0.4;
    ctx.beginPath();
    for (const n of nodes) {
      if (n.brand !== brand) continue;
      // A fixed size keeps the brand accent equally visible on every load.
      const r = brand ? BRAND_RADIUS : n.r;
      ctx.moveTo(n.x + r, n.y);
      ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
    }
    ctx.fill();
  }
  ctx.globalAlpha = 1;
}

/**
 * Decorative backdrop of the screens outside the shell (sign-in, reset,
 * setup): small nodes drifting across the viewport, linked when they pass
 * close, like the ICS mark coming apart. Under reduced motion it paints
 * one still frame.
 */
export function BackgroundGraph() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  // A still backdrop has no next frame to pick up a theme change: repaint it.
  const repaint = useRef<(() => void) | null>(null);
  const palette = usePalette(() => repaint.current?.());

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;

    const still = prefersReducedMotion();
    let nodes: DriftNode[] = [];
    let raf = 0;

    let lastW = 0;
    let lastH = 0;
    /** Matches the bitmap to the element. Runs inside the frame: animation
     * frames see a new size before ResizeObserver does, and would wrap the
     * nodes of a wide layout off a narrow one before they were scaled. */
    const fit = (w: number, h: number) => {
      if (w === lastW && h === lastH) return;
      if (lastW > 0 && lastH > 0) scaleNodes(nodes, w / lastW, h / lastH);
      lastW = w;
      lastH = h;
      const dpr = window.devicePixelRatio || 1;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const frame = () => {
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      if (w > 0 && h > 0) {
        fit(w, h);
        if (nodes.length === 0) nodes = seedNodes(w, h);
        if (!still) stepNodes(nodes, w, h);
        draw(ctx, nodes, w, h, palette.current);
      }
      if (!still) raf = requestAnimationFrame(frame);
    };

    // An animated backdrop picks the new size up on its next frame; a still one needs a repaint.
    const resize = new ResizeObserver(() => {
      if (still) frame();
    });
    resize.observe(canvas);
    if (still) repaint.current = frame;

    frame();
    return () => {
      cancelAnimationFrame(raf);
      resize.disconnect();
      repaint.current = null;
    };
  }, [palette]);

  return <canvas ref={canvasRef} aria-hidden className="pointer-events-none fixed inset-0 size-full" />;
}
