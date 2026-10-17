import { useCallback, useEffect, useId, useRef, useState, type ReactNode, type Ref } from "react";
import { createPortal } from "react-dom";
import { clsx } from "clsx";
import { useEnterMotion } from "../../lib/motion";
import { MOBILE_QUERY, useMediaQuery } from "../../lib/useMediaQuery";
import { useAnchoredPosition, type Align } from "./floating";
import { Sheet } from "./Sheet";
import { useOverlay } from "./useOverlay";

interface PopoverTriggerProps {
  ref: Ref<HTMLButtonElement>;
  onClick: () => void;
  "aria-haspopup": "dialog";
  "aria-expanded": boolean;
  "aria-controls": string | undefined;
}

interface Props {
  /** Accessible name of the panel, and the sheet title on phones. */
  label: string;
  trigger: (props: PopoverTriggerProps) => ReactNode;
  children: (api: { close: () => void }) => ReactNode;
  align?: Align;
  /** Panel width on devices with room. */
  widthClass?: string;
  /** Sticky footer (Clear / Apply). */
  footer?: (api: { close: () => void }) => ReactNode;
}

/**
 * Anchored panel with free content (filters, a small form). On phones it
 * becomes a bottom sheet with the same content. Focus moves into the panel
 * and returns to the trigger on close.
 */
export function Popover({ label, trigger, children, align = "start", widthClass = "w-80", footer }: Props) {
  const [open, setOpen] = useState(false);
  const phone = useMediaQuery(MOBILE_QUERY);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const id = useId();
  const close = useCallback(() => setOpen(false), []);
  const anchored = open && !phone;

  useAnchoredPosition(triggerRef, panelRef, anchored, { side: "bottom", align });
  useOverlay(panelRef, anchored, { onClose: close });
  useEnterMotion(panelRef, "menu", anchored);

  useEffect(() => {
    if (!anchored) return;
    const onPointer = (e: PointerEvent) => {
      const node = e.target as Node;
      if (!panelRef.current?.contains(node) && !triggerRef.current?.contains(node)) close();
    };
    document.addEventListener("pointerdown", onPointer);
    return () => document.removeEventListener("pointerdown", onPointer);
  }, [anchored, close]);

  return (
    <>
      {trigger({
        ref: triggerRef,
        onClick: () => setOpen((v) => !v),
        "aria-haspopup": "dialog",
        "aria-expanded": open,
        "aria-controls": anchored ? id : undefined,
      })}
      {anchored &&
        createPortal(
          <div
            ref={panelRef}
            id={id}
            role="dialog"
            aria-label={label}
            className={clsx(
              "fixed z-[60] flex max-h-[min(34rem,calc(100dvh-2rem))] max-w-[calc(100vw-1rem)] flex-col",
              "rounded-card border border-border bg-surface shadow-floating",
              widthClass,
            )}
          >
            <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-3">{children({ close })}</div>
            {footer && <div className="border-t border-border px-3 py-2.5">{footer({ close })}</div>}
          </div>,
          document.body,
        )}
      {phone && (
        <Sheet open={open} title={label} onClose={close} footer={footer?.({ close })}>
          {children({ close })}
        </Sheet>
      )}
    </>
  );
}
