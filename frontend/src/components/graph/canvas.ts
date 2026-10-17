/**
 * React plumbing shared by the graph canvases: devicePixelRatio sizing,
 * theme palette, and an on-demand rAF loop. Callers keep the simulation in
 * refs and redraw only when `invalidate()` says something changed.
 */
import { useEffect, useRef, useState, type RefObject } from "react";

import type { Point } from "./interactions";
import { PALETTE_FALLBACK, readPalette, type Palette } from "./render";
import type { Size } from "./types";

/** Sizes the backing store for crisp lines on HiDPI screens; drawing stays in CSS pixels. */
export function sizeCanvas(canvas: HTMLCanvasElement, size: Size): void {
  const dpr = window.devicePixelRatio || 1;
  canvas.width = size.w * dpr;
  canvas.height = size.h * dpr;
  canvas.style.width = `${size.w}px`;
  canvas.style.height = `${size.h}px`;
  canvas.getContext("2d")?.setTransform(dpr, 0, 0, dpr, 0, 0);
}

/** Client coordinates of a pointer event to canvas-relative screen coordinates. */
export function toScreen(
  canvas: HTMLCanvasElement | null,
  e: { clientX: number; clientY: number },
): Point {
  const r = canvas?.getBoundingClientRect();
  return r ? { x: e.clientX - r.left, y: e.clientY - r.top } : { x: 0, y: 0 };
}

/** Keeps the latest callback in a ref, so long-lived listeners never go stale. */
function useLatest<T>(value: T): RefObject<T> {
  const ref = useRef(value);
  useEffect(() => {
    ref.current = value;
  });
  return ref;
}

/**
 * Tracks the wrapper's size and resizes the canvas to fill it. Resizing
 * clears the canvas, so `onResize` is where the caller schedules a redraw.
 */
export function useCanvasSize(
  wrapRef: RefObject<HTMLElement | null>,
  canvasRef: RefObject<HTMLCanvasElement | null>,
  initial: Size,
  onResize?: (size: Size) => void,
): RefObject<Size> {
  const size = useRef(initial);
  const onResizeRef = useLatest(onResize);
  useEffect(() => {
    const wrap = wrapRef.current;
    const canvas = canvasRef.current;
    if (!wrap || !canvas || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => {
      const r = wrap.getBoundingClientRect();
      size.current = { w: r.width, h: r.height };
      sizeCanvas(canvas, size.current);
      onResizeRef.current?.(size.current);
    });
    ro.observe(wrap);
    return () => ro.disconnect();
  }, [wrapRef, canvasRef, onResizeRef]);
  return size;
}

/**
 * Theme colours for the canvas, read once and again only when the theme
 * changes (explicit switch or system preference): each read forces a style
 * recalculation. `onChange` lets the caller redraw with the new colours.
 */
export function usePalette(onChange?: () => void): RefObject<Palette> {
  const palette = useRef<Palette>(PALETTE_FALLBACK);
  const onChangeRef = useLatest(onChange);
  useEffect(() => {
    const refresh = () => {
      palette.current = readPalette();
      onChangeRef.current?.();
    };
    refresh();
    const observer = new MutationObserver(refresh);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    media?.addEventListener("change", refresh);
    return () => {
      observer.disconnect();
      media?.removeEventListener("change", refresh);
    };
  }, [onChangeRef]);
  return palette;
}

/** Size of an element, kept current with a ResizeObserver; zero until measured. */
export function useElementSize(ref: RefObject<HTMLElement | null>): Size {
  const [size, setSize] = useState<Size>({ w: 0, h: 0 });
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => {
      const r = el.getBoundingClientRect();
      setSize((prev) => (prev.w === r.width && prev.h === r.height ? prev : { w: r.width, h: r.height }));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return size;
}

/**
 * A value derived from the element's size, kept only when it changes: a
 * resize re-renders the caller only when the derived value does. `derive`
 * should be stable (`useCallback`); a new one measures again.
 */
export function useMeasured<T>(ref: RefObject<HTMLElement | null>, derive: (size: Size) => T, initial: T): T {
  const [value, setValue] = useState<T>(initial);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => {
      const r = el.getBoundingClientRect();
      setValue(derive({ w: r.width, h: r.height }));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref, derive]);
  return value;
}

/** Handle of an on-demand animation loop, see `useRenderLoop`. */
export interface RenderLoop {
  /** Marks the scene dirty: schedules a frame unless one is pending. */
  invalidate: () => void;
  /** Sets the frame: draws one and returns whether another is needed. Used by `useFrame`. */
  setFrame: (frame: () => boolean) => void;
}

/**
 * On-demand animation loop. The frame registered with `useFrame` runs while
 * it returns true (physics still moving); the loop then idles until
 * `invalidate()` marks the scene dirty again. Created before the palette and
 * size hooks so they can take `invalidate` as their change callback.
 */
export function useRenderLoop(): RenderLoop {
  const raf = useRef(0);
  const [loop] = useState<RenderLoop>(() => {
    let frame = () => false;
    return {
      setFrame: (f) => {
        frame = f;
      },
      invalidate: () => {
        if (raf.current) return;
        const tick = () => {
          raf.current = 0;
          if (frame()) raf.current = requestAnimationFrame(tick);
        };
        raf.current = requestAnimationFrame(tick);
      },
    };
  });
  useEffect(
    () => () => {
      cancelAnimationFrame(raf.current);
      raf.current = 0;
    },
    [],
  );
  return loop;
}

/** Registers the loop's frame (latest closure wins) and draws the first one on mount. */
export function useFrame(loop: RenderLoop, frame: () => boolean): void {
  useEffect(() => loop.setFrame(frame));
  useEffect(() => loop.invalidate(), [loop]);
}
