import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
  type Ref,
} from "react";
import { createPortal } from "react-dom";
import { clsx } from "clsx";
import { Check, MoreHorizontal } from "lucide-react";
import { useEnterMotion } from "../../lib/motion";
import { MOBILE_QUERY, useMediaQuery } from "../../lib/useMediaQuery";
import { ActionSheet } from "./ActionSheet";
import { iconButtonClass } from "./IconButton";
import { useAnchoredPosition, type Align } from "./floating";
import type { MenuAction } from "./menuAction";
import { useOverlay } from "./useOverlay";

export interface MenuTriggerProps {
  ref: Ref<HTMLButtonElement>;
  onClick: () => void;
  onKeyDown: (e: KeyboardEvent<HTMLButtonElement>) => void;
  "aria-haspopup": "menu";
  "aria-expanded": boolean;
  "aria-controls": string | undefined;
}

interface Props {
  /** Name of the menu, and title of the sheet on phones. */
  label: string;
  actions: readonly MenuAction[];
  /** Renders the trigger; spread the props onto a button. Defaults to the
   * row `…` icon button named by `label`. */
  trigger?: (props: MenuTriggerProps) => ReactNode;
  align?: Align;
  /** Extra line on top of the list, e.g. why an option is missing. */
  note?: string;
}

/**
 * The action menu of the app: a dropdown next to the trigger on devices
 * with room, the bottom action sheet on phones. Both render the same
 * `MenuAction` list, so a feature cannot exist in one form and not the
 * other. Arrow keys move, Home/End jump, Escape and Tab close.
 */
export function Menu({ label, actions, trigger, align = "end", note }: Props) {
  const renderTrigger =
    trigger ??
    ((props: MenuTriggerProps) => (
      <button type="button" {...props} aria-label={label} className={iconButtonClass("ghost", "sm")}>
        <MoreHorizontal size={18} aria-hidden />
      </button>
    ));
  const [open, setOpen] = useState(false);
  const [focusLast, setFocusLast] = useState(false);
  const phone = useMediaQuery(MOBILE_QUERY);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const id = useId();
  const close = useCallback(() => setOpen(false), []);
  const dropdown = open && !phone;

  useAnchoredPosition(triggerRef, listRef, dropdown, { side: "bottom", align });
  useOverlay(listRef, dropdown, { onClose: close, keepFocus: true });
  useEnterMotion(listRef, "menu", dropdown);

  useEffect(() => {
    if (!dropdown) return;
    const items = listRef.current?.querySelectorAll<HTMLElement>("[data-menu-item]");
    const checked = listRef.current?.querySelector<HTMLElement>("[aria-checked='true']");
    const target = checked ?? (focusLast ? items?.[items.length - 1] : items?.[0]);
    target?.focus({ preventScroll: true });
    const onPointer = (e: PointerEvent) => {
      const node = e.target as Node;
      if (!listRef.current?.contains(node) && !triggerRef.current?.contains(node)) close();
    };
    document.addEventListener("pointerdown", onPointer);
    return () => document.removeEventListener("pointerdown", onPointer);
  }, [dropdown, focusLast, close]);

  const onListKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const items = [...(listRef.current?.querySelectorAll<HTMLElement>("[data-menu-item]") ?? [])];
    const at = items.indexOf(document.activeElement as HTMLElement);
    const move = (i: number) => items[(i + items.length) % items.length]?.focus();
    if (e.key === "ArrowDown") move(at + 1);
    else if (e.key === "ArrowUp") move(at - 1);
    else if (e.key === "Home") move(0);
    else if (e.key === "End") move(items.length - 1);
    else if (e.key === "Tab") {
      close();
      return;
    } else return;
    e.preventDefault();
  };

  const pick = (act: MenuAction) => {
    if (act.disabled) return;
    close();
    act.onClick();
  };

  return (
    <>
      {renderTrigger({
        ref: triggerRef,
        onClick: () => {
          setFocusLast(false);
          setOpen((v) => !v);
        },
        onKeyDown: (e) => {
          if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
          e.preventDefault();
          setFocusLast(e.key === "ArrowUp");
          setOpen(true);
        },
        "aria-haspopup": "menu",
        "aria-expanded": open,
        "aria-controls": dropdown ? id : undefined,
      })}
      {dropdown &&
        createPortal(
          <div
            ref={listRef}
            id={id}
            role="menu"
            aria-label={label}
            onKeyDown={onListKey}
            className="fixed z-[60] w-64 max-w-[calc(100vw-1rem)] max-h-[min(28rem,calc(100dvh-2rem))] overflow-y-auto rounded-card border border-border bg-surface p-1 shadow-floating"
          >
            {note && <p className="px-2.5 pb-1 pt-1.5 text-meta text-text-secondary">{note}</p>}
            {actions.map((act) => (
              <MenuEntry key={act.key} action={act} onPick={() => pick(act)} />
            ))}
          </div>,
          document.body,
        )}
      {phone && <ActionSheet open={open} title={label} actions={actions} onClose={close} />}
    </>
  );
}

function MenuEntry({ action: act, onPick }: { action: MenuAction; onPick: () => void }) {
  return (
    <>
      {act.heading && (
        <>
          <div className="mx-1 my-1 h-px bg-border" role="separator" />
          <p role="presentation" className="px-2.5 pb-1 pt-1.5 text-meta font-medium text-text-secondary">
            {act.heading}
          </p>
        </>
      )}
      <button
        type="button"
        data-menu-item
        role={act.checked === undefined ? "menuitem" : "menuitemradio"}
        aria-checked={act.checked}
        aria-disabled={act.disabled || undefined}
        tabIndex={-1}
        onClick={onPick}
        title={act.disabled ? act.disabledHint : undefined}
        className={clsx(
          "flex w-full items-center gap-2.5 rounded-control px-2.5 py-2 text-left text-ui outline-none",
          "transition-colors duration-100 hover:bg-surface-hover focus-visible:bg-surface-hover focus:bg-surface-hover",
          "aria-disabled:cursor-not-allowed aria-disabled:opacity-45",
          act.danger ? "text-danger" : "text-text-primary",
        )}
      >
        {act.icon && (
          <act.icon
            size={16}
            aria-hidden
            className={clsx("shrink-0", act.danger ? "text-danger" : act.checked ? "text-accent" : "text-text-secondary")}
          />
        )}
        <span className="min-w-0 flex-1 truncate">{act.label}</span>
        {act.checked && <Check size={16} aria-hidden className="shrink-0 text-accent" />}
      </button>
    </>
  );
}
