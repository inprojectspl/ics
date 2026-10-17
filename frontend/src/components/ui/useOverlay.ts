import { useEffect, useLayoutEffect, useRef, type RefObject } from "react";
import { FOCUSABLE } from "./floating";

// Open overlays, innermost last: Escape closes only the top one, so a menu
// inside a dialog closes the menu and leaves the dialog alone.
const stack: symbol[] = [];
let locks = 0;
let saved: { overflow: string; overscroll: string } | null = null;

function lockScroll() {
  if (locks++ > 0) return;
  const { body, documentElement: html } = document;
  saved = { overflow: body.style.overflow, overscroll: html.style.overscrollBehavior };
  body.style.overflow = "hidden";
  html.style.overscrollBehavior = "none";
}

function unlockScroll() {
  if (--locks > 0 || !saved) return;
  document.body.style.overflow = saved.overflow;
  document.documentElement.style.overscrollBehavior = saved.overscroll;
  saved = null;
}

/** Whether an overlay is open: a page-level Escape (leaving a mode) waits until none is. */
export function overlayOpen(): boolean {
  return stack.length > 0;
}

interface Options {
  onClose: () => void;
  /** Modal overlays (dialog, drawer, sheet) lock the page scroll. */
  modal?: boolean;
  /** Where focus goes on open; the first focusable element when omitted. */
  initialFocus?: RefObject<HTMLElement | null>;
  /** Leave focus where it is (menus move it themselves). */
  keepFocus?: boolean;
}

/**
 * Shared behaviour of every overlay: Escape (innermost first), page scroll
 * lock for modal ones, focus moved inside on open and handed back to the
 * element that opened it on close. Takes effect the moment the overlay
 * mounts, independent of any entrance animation.
 */
export function useOverlay(
  containerRef: RefObject<HTMLElement | null>,
  open: boolean,
  { onClose, modal = false, initialFocus, keepFocus = false }: Options,
): void {
  const onCloseRef = useRef(onClose);
  useLayoutEffect(() => {
    onCloseRef.current = onClose;
  });

  useEffect(() => {
    if (!open) return;
    const id = Symbol("overlay");
    stack.push(id);
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || stack[stack.length - 1] !== id) return;
      e.stopPropagation();
      onCloseRef.current();
    };
    document.addEventListener("keydown", onKey);
    if (modal) lockScroll();
    return () => {
      const at = stack.indexOf(id);
      if (at !== -1) stack.splice(at, 1);
      document.removeEventListener("keydown", onKey);
      if (modal) unlockScroll();
    };
  }, [open, modal]);

  useEffect(() => {
    if (!open) return;
    const container = containerRef.current;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    if (!keepFocus) {
      const target =
        initialFocus?.current ?? container?.querySelector<HTMLElement>(FOCUSABLE);
      (target ?? container)?.focus({ preventScroll: true });
    }
    return () => {
      // Only when focus is still inside (or lost to <body>): a click that
      // moved focus elsewhere on purpose must not be undone.
      const active = document.activeElement;
      const inside = !active || active === document.body || container?.contains(active);
      if (inside && opener?.isConnected) opener.focus({ preventScroll: true });
    };
  }, [open, keepFocus, initialFocus, containerRef]);
}
