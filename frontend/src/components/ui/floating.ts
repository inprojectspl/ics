import { useLayoutEffect, type KeyboardEvent as ReactKeyboardEvent, type RefObject } from "react";

export type Side = "bottom" | "top" | "right" | "left";
export type Align = "start" | "end" | "center";

interface Options {
  side?: Side;
  align?: Align;
  /** Gap between the anchor and the floating element, in px. */
  offset?: number;
  /** Match the anchor's width (select-like popovers). */
  matchWidth?: boolean;
}

const MARGIN = 8;

/**
 * Keeps a portalled floating element next to its anchor, flipping and
 * clamping into the viewport. Writes the style directly: a state round trip
 * would paint one frame at the wrong spot.
 */
export function useAnchoredPosition(
  anchorRef: RefObject<HTMLElement | null>,
  floatingRef: RefObject<HTMLElement | null>,
  open: boolean,
  { side = "bottom", align = "start", offset = 6, matchWidth = false }: Options = {},
): void {
  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const anchor = anchorRef.current;
      const el = floatingRef.current;
      if (!anchor || !el) return;
      const a = anchor.getBoundingClientRect();
      if (matchWidth) el.style.minWidth = `${a.width}px`;
      const f = el.getBoundingClientRect();
      const vw = document.documentElement.clientWidth;
      const vh = window.innerHeight;
      let top: number;
      let left: number;
      if (side === "bottom" || side === "top") {
        const below = a.bottom + offset;
        const above = a.top - offset - f.height;
        const fitsBelow = below + f.height <= vh - MARGIN;
        const fitsAbove = above >= MARGIN;
        top = side === "bottom" ? (fitsBelow || !fitsAbove ? below : above) : fitsAbove || !fitsBelow ? above : below;
        left = align === "start" ? a.left : align === "end" ? a.right - f.width : a.left + (a.width - f.width) / 2;
      } else {
        const right = a.right + offset;
        const leftSide = a.left - offset - f.width;
        left = side === "right" ? (right + f.width <= vw - MARGIN ? right : leftSide) : leftSide >= MARGIN ? leftSide : right;
        top = align === "start" ? a.top : align === "end" ? a.bottom - f.height : a.top + (a.height - f.height) / 2;
      }
      left = Math.min(Math.max(MARGIN, left), vw - f.width - MARGIN);
      top = Math.min(Math.max(MARGIN, top), vh - f.height - MARGIN);
      el.style.left = `${Math.round(left)}px`;
      el.style.top = `${Math.round(top)}px`;
    };
    place();
    // Scroll fires many times a frame; measuring once per frame is enough.
    let frame = 0;
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(() => {
        frame = 0;
        place();
      });
    };
    window.addEventListener("resize", schedule);
    // Capture: a scroll inside any container (the sidebar, a panel) moves the anchor too.
    window.addEventListener("scroll", schedule, true);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", schedule);
      window.removeEventListener("scroll", schedule, true);
    };
  }, [anchorRef, floatingRef, open, side, align, offset, matchWidth]);
}

/** Selector of everything that can take keyboard focus inside a container. */
export const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** Keeps Tab inside `container` (dialogs, drawers, sheets). */
export function trapTab(e: KeyboardEvent | ReactKeyboardEvent, container: HTMLElement | null): void {
  if (e.key !== "Tab" || !container) return;
  const items = [...container.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(
    (el) => el.offsetParent !== null || el === document.activeElement,
  );
  const first = items[0];
  const last = items[items.length - 1];
  if (!first || !last) {
    e.preventDefault();
    return;
  }
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault();
    first.focus();
  }
}
