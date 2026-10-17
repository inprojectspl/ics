import { useEffect, type RefObject } from "react";
import { wheelFactor } from "../graph/cardViewport";

/** The part of pdf.js `PDFViewer` the gestures drive. */
export interface ScalableViewer {
  updateScale(options: { scaleFactor: number; origin: number[]; drawingDelay: number }): void;
}

// While fingers or the wheel move, pages are scaled with CSS and redrawn
// only after the gesture pauses this long.
const DRAWING_DELAY_MS = 400;

function distance(a: Touch, b: Touch): number {
  return Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
}

/** Pinch to zoom on touch screens and Ctrl/Cmd + wheel (a trackpad pinch
 * too) on desktop, around the gesture's centre. The viewer is read from
 * `live` when a gesture happens, so it may be set after the effect runs. */
export function useViewerGestures(
  containerRef: RefObject<HTMLElement | null>,
  live: RefObject<{ viewer: ScalableViewer } | null>,
): void {
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    let last = 0;

    const onWheel = (e: WheelEvent) => {
      const v = live.current?.viewer;
      if (!v || !(e.ctrlKey || e.metaKey)) return;
      e.preventDefault();
      v.updateScale({
        scaleFactor: wheelFactor(e),
        origin: [e.clientX, e.clientY],
        drawingDelay: DRAWING_DELAY_MS,
      });
    };
    const onTouchStart = (e: TouchEvent) => {
      const [a, b] = [e.touches[0], e.touches[1]];
      last = e.touches.length === 2 && a && b ? distance(a, b) : 0;
    };
    const onTouchMove = (e: TouchEvent) => {
      const v = live.current?.viewer;
      const [a, b] = [e.touches[0], e.touches[1]];
      if (!v || e.touches.length !== 2 || !a || !b || last === 0) return;
      e.preventDefault();
      const now = distance(a, b);
      v.updateScale({
        scaleFactor: now / last,
        origin: [(a.clientX + b.clientX) / 2, (a.clientY + b.clientY) / 2],
        drawingDelay: DRAWING_DELAY_MS,
      });
      last = now;
    };
    const onTouchEnd = () => {
      last = 0;
    };

    // Not passive: the page itself must not zoom or scroll under the gesture.
    el.addEventListener("wheel", onWheel, { passive: false });
    el.addEventListener("touchstart", onTouchStart, { passive: true });
    el.addEventListener("touchmove", onTouchMove, { passive: false });
    el.addEventListener("touchend", onTouchEnd);
    el.addEventListener("touchcancel", onTouchEnd);
    return () => {
      el.removeEventListener("wheel", onWheel);
      el.removeEventListener("touchstart", onTouchStart);
      el.removeEventListener("touchmove", onTouchMove);
      el.removeEventListener("touchend", onTouchEnd);
      el.removeEventListener("touchcancel", onTouchEnd);
    };
  }, [containerRef, live]);
}
