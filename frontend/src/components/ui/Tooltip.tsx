import { useCallback, useEffect, useId, useRef, useState, type FocusEvent, type PointerEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useAnchoredPosition, type Side } from "./floating";

const HOVER_DELAY = 350;

export interface TooltipTriggerProps {
  onPointerEnter: (e: PointerEvent<HTMLElement>) => void;
  onPointerLeave: () => void;
  onFocus: (e: FocusEvent<HTMLElement>) => void;
  onBlur: () => void;
  "aria-describedby"?: string;
}

/**
 * Short label on hover (real hover devices only) and keyboard focus; repeats
 * the trigger's accessible name visually unless `describe` is set. Portalled
 * so scroll containers do not clip it.
 */
export function useTooltip(label: string, { side = "top", describe = false }: { side?: Side; describe?: boolean } = {}): {
  triggerProps: TooltipTriggerProps;
  bubble: ReactNode;
} {
  const [open, setOpen] = useState(false);
  const anchorRef = useRef<HTMLElement | null>(null);
  const tipRef = useRef<HTMLDivElement>(null);
  const timer = useRef<number | undefined>(undefined);
  const id = useId();
  useAnchoredPosition(anchorRef, tipRef, open, { side, align: "center", offset: 8 });

  const hide = useCallback(() => {
    window.clearTimeout(timer.current);
    setOpen(false);
  }, []);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") hide();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, hide]);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  const onPointerEnter = useCallback((e: PointerEvent<HTMLElement>) => {
    // The anchor comes from the event, so the trigger keeps its own ref.
    anchorRef.current = e.currentTarget;
    if (e.pointerType !== "mouse") return;
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setOpen(true), HOVER_DELAY);
  }, []);
  const onFocus = useCallback((e: FocusEvent<HTMLElement>) => {
    anchorRef.current = e.currentTarget;
    if (e.currentTarget.matches(":focus-visible")) setOpen(true);
  }, []);

  const bubble = open
    ? createPortal(
        <div
          ref={tipRef}
          id={id}
          role="tooltip"
          aria-hidden={!describe}
          className="pointer-events-none fixed z-[70] max-w-64 rounded-xs bg-text-primary px-2 py-1 text-meta font-medium text-surface shadow-floating"
        >
          {label}
        </div>,
        document.body,
      )
    : describe && (
        <span id={id} hidden>
          {label}
        </span>
      );

  return {
    triggerProps: {
      onPointerEnter,
      onPointerLeave: hide,
      onFocus,
      onBlur: hide,
      "aria-describedby": describe ? id : undefined,
    },
    bubble,
  };
}
