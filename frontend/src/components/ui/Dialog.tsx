import { useId, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { clsx } from "clsx";
import { X } from "lucide-react";
import { t } from "../../lib/i18n";
import { useEnterMotion } from "../../lib/motion";
import { trapTab } from "./floating";
import { IconButton } from "./IconButton";
import { useOverlay } from "./useOverlay";

interface Props {
  title: ReactNode;
  /** Context line above the title (the document the dialog acts on). */
  eyebrow?: ReactNode;
  onClose: () => void;
  maxWidth?: "md" | "lg" | "xl" | "2xl";
  children: ReactNode;
}

const MAX_W: Record<NonNullable<Props["maxWidth"]>, string> = {
  md: "sm:max-w-md",
  lg: "sm:max-w-lg",
  xl: "sm:max-w-xl",
  "2xl": "sm:max-w-2xl",
};

/**
 * A focused decision or edit over the page: centred card on wider screens,
 * a full-width sheet from the bottom on phones. The body scrolls inside
 * the dialog; the page behind is locked. Callers mount it while open.
 */
export function Dialog({ title, eyebrow, onClose, maxWidth = "xl", children }: Props) {
  const panelRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useOverlay(panelRef, true, { onClose, modal: true });
  useEnterMotion(panelRef, "dialog");

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-6" role="presentation">
      <div aria-hidden onClick={onClose} className="absolute inset-0 bg-scrim" />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        onKeyDown={(e) => trapTab(e, panelRef.current)}
        className={clsx(
          "relative flex w-full flex-col bg-surface shadow-floating outline-none",
          "max-h-[92dvh] rounded-t-overlay sm:max-h-[88dvh] sm:rounded-overlay sm:border sm:border-border",
          MAX_W[maxWidth],
        )}
      >
        <header className="flex shrink-0 items-start justify-between gap-3 border-b border-border py-3 pl-5 pr-3 sm:pl-6">
          <div className="min-w-0 pt-1">
            {eyebrow && <p className="truncate text-meta text-text-secondary">{eyebrow}</p>}
            <h2 id={titleId} className="text-title font-semibold text-text-primary [overflow-wrap:anywhere]">
              {title}
            </h2>
          </div>
          <IconButton label={t("common.close")} icon={<X size={18} aria-hidden />} onClick={onClose} noTooltip />
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain pb-[env(safe-area-inset-bottom)]">
          {children}
        </div>
      </div>
    </div>,
    document.body,
  );
}
