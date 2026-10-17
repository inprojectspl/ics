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
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}

/** Bottom sheet with free content: the phone form of `Popover` and of
 * panels that sit beside the content on wider screens. */
export function Sheet({ open, title, onClose, children, footer }: Props) {
  const panelRef = useRef<HTMLDivElement>(null);
  const shown = usePresence(open, panelRef, "sheet");
  useOverlay(panelRef, open, { onClose, modal: true });
  if (!shown) return null;

  return createPortal(
    <div className="fixed inset-0 z-[60] flex items-end" role="presentation">
      <div aria-hidden onClick={onClose} className={clsx(
          "absolute inset-0 bg-scrim transition-opacity duration-200 ease-standard",
          open ? "opacity-100" : "opacity-0",
        )} />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        onKeyDown={(e) => trapTab(e, panelRef.current)}
        className="relative flex max-h-[88dvh] w-full flex-col rounded-t-overlay bg-surface shadow-floating outline-none"
      >
        <div className="flex items-center justify-between gap-3 border-b border-border py-2 pl-5 pr-2">
          <h2 className="truncate text-body font-semibold text-text-primary">{title}</h2>
          <IconButton label={t("common.close")} icon={<X size={18} aria-hidden />} onClick={onClose} noTooltip />
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 py-4">{children}</div>
        {footer && (
          <div className="border-t border-border px-5 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3">
            {footer}
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}
