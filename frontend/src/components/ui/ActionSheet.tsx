import { useRef } from "react";
import { createPortal } from "react-dom";
import { clsx } from "clsx";
import { Check } from "lucide-react";
import { usePresence } from "../../lib/motion";
import type { MenuAction } from "./menuAction";
import { trapTab } from "./floating";
import { useOverlay } from "./useOverlay";

interface Props {
  open: boolean;
  title: string;
  actions: readonly MenuAction[];
  onClose: () => void;
}

/**
 * Bottom action sheet, the phone form of `Menu`: the same actions as the
 * desktop dropdown, as full-width labelled rows with 48 px targets.
 * Portalled to <body> so no transformed ancestor traps the fixed overlay.
 */
export function ActionSheet({ open, title, actions, onClose }: Props) {
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
        className={clsx(
          "relative w-full max-h-[85dvh] overflow-y-auto overscroll-contain bg-surface",
          "rounded-t-overlay shadow-floating outline-none",
          "pt-2 pb-[max(0.75rem,env(safe-area-inset-bottom))]",
        )}
      >
        <div className="mx-auto mb-1 mt-1 h-1 w-9 rounded-full bg-border-strong" aria-hidden />
        <p className="truncate px-5 pb-2 pt-1 text-meta font-medium text-text-secondary">{title}</p>
        <ul role="menu" aria-label={title}>
          {actions.map((act) => (
            <li key={act.key} role="none">
              {act.heading && (
                <p
                  role="presentation"
                  className="mt-1 border-t border-border px-5 pb-1 pt-3 text-meta font-medium text-text-secondary"
                >
                  {act.heading}
                </p>
              )}
              <button
                type="button"
                role={act.checked === undefined ? "menuitem" : "menuitemradio"}
                aria-checked={act.checked}
                disabled={act.disabled}
                onClick={() => {
                  if (act.disabled) return;
                  onClose();
                  act.onClick();
                }}
                className={clsx(
                  "flex min-h-12 w-full items-center gap-3 px-5 py-2.5 text-left text-body",
                  "transition-colors duration-150 active:bg-surface-hover disabled:opacity-40",
                  act.danger ? "text-danger" : "text-text-primary",
                )}
              >
                {act.icon && <act.icon size={18} aria-hidden className="shrink-0 text-current opacity-80" />}
                <span className="min-w-0 flex-1">
                  <span className="block truncate">{act.label}</span>
                  {act.disabled && act.disabledHint && (
                    <span className="block text-meta text-text-secondary">{act.disabledHint}</span>
                  )}
                </span>
                {act.checked && <Check size={18} aria-hidden className="shrink-0 text-accent" />}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>,
    document.body,
  );
}
