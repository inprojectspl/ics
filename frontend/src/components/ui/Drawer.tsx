import { useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { clsx } from "clsx";
import { X } from "lucide-react";
import { t } from "../../lib/i18n";
import { usePresence } from "../../lib/motion";
import { trapTab } from "./floating";
import { IconButton } from "./IconButton";
import { useOverlay } from "./useOverlay";

interface Props {
  open: boolean;
  onClose: () => void;
  /** Accessible name; shown as the heading unless `header` replaces it. */
  title: string;
  side?: "left" | "right";
  /** Custom header content (the navigation drawer shows the brand). */
  header?: ReactNode;
  widthClass?: string;
  id?: string;
  children: ReactNode;
}

/**
 * Off-canvas panel over the page: the navigation on phones, the document
 * inspector on narrow screens. Focus moves in on open and back to the
 * opener on close; Escape, the close button and the backdrop close it.
 */
export function Drawer({
  open,
  onClose,
  title,
  side = "left",
  header,
  widthClass = "w-[min(20rem,86vw)]",
  id,
  children,
}: Props) {
  const panelRef = useRef<HTMLDivElement>(null);
  const shown = usePresence(open, panelRef, side === "left" ? "drawer-left" : "drawer-right");
  useOverlay(panelRef, open, { onClose, modal: true });
  if (!shown) return null;

  return createPortal(
    <div className="fixed inset-0 z-50" role="presentation">
      <div aria-hidden onClick={onClose} className={clsx(
          "absolute inset-0 bg-scrim transition-opacity duration-200 ease-standard",
          open ? "opacity-100" : "opacity-0",
        )} />
      <div
        ref={panelRef}
        id={id}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        onKeyDown={(e) => trapTab(e, panelRef.current)}
        className={clsx(
          "absolute inset-y-0 flex flex-col bg-surface shadow-floating outline-none",
          "pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)]",
          side === "left" ? "left-0 border-r border-border" : "right-0 border-l border-border",
          widthClass,
        )}
      >
        <div className="flex h-14 shrink-0 items-center justify-between gap-2 border-b border-border pl-4 pr-2">
          <div className="min-w-0 flex-1">
            {header ?? <h2 className="truncate text-body font-semibold text-text-primary">{title}</h2>}
          </div>
          <IconButton label={t("common.close")} icon={<X size={18} aria-hidden />} onClick={onClose} noTooltip />
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">{children}</div>
      </div>
    </div>,
    document.body,
  );
}
