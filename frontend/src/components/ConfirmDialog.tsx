import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { clsx } from "clsx";
import { t } from "../lib/i18n";
import { Dialog } from "./ui/Dialog";

interface ConfirmOptions {
  title: string;
  message?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Destructive variant paints the confirm button in `danger` and lets
   * the user know they're about to lose something. Defaults to false. */
  destructive?: boolean;
}

type ConfirmFn = (options: ConfirmOptions) => Promise<boolean>;

const ConfirmCtx = createContext<ConfirmFn | null>(null);

/** Async drop-in replacement for `window.confirm`. Renders the prompt in
 * a stylised Modal and resolves to true/false. */
export function useConfirm(): ConfirmFn {
  const v = useContext(ConfirmCtx);
  if (!v) {
    throw new Error("useConfirm() must be used inside <ConfirmProvider>");
  }
  return v;
}

interface PendingState {
  options: ConfirmOptions;
  resolve: (ok: boolean) => void;
}

export function ConfirmProvider({ children }: { children: ReactNode }) {
  // One prompt at a time: a second one cancels the first instead of queuing.
  const [pending, setPending] = useState<PendingState | null>(null);
  const confirmBtnRef = useRef<HTMLButtonElement | null>(null);

  const confirm = useCallback<ConfirmFn>(
    (options) =>
      new Promise<boolean>((resolve) => {
        setPending((prev) => {
          prev?.resolve(false);
          return { options, resolve };
        });
      }),
    [],
  );

  const close = useCallback(
    (ok: boolean) => {
      if (!pending) return;
      pending.resolve(ok);
      setPending(null);
    },
    [pending],
  );

  // Enter confirms even when the confirm button is not focused; Escape is
  // handled by the modal.
  useEffect(() => {
    if (!pending) return;
    confirmBtnRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Enter") {
        e.preventDefault();
        close(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pending, close]);

  return (
    <ConfirmCtx.Provider value={confirm}>
      {children}
      {pending && (
        <Dialog
          title={pending.options.title}
          onClose={() => close(false)}
          maxWidth="md"
        >
          <div className="px-6 py-5 space-y-5">
            {pending.options.message && (
              <div className="text-text-secondary text-ui leading-relaxed whitespace-pre-line">
                {pending.options.message}
              </div>
            )}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => close(false)}
                className={clsx(
                  "inline-flex items-center justify-center h-10 px-4 rounded-control",
                  "text-ui font-medium",
                  "text-text-secondary hover:text-text-primary hover:bg-surface-subtle transition-colors",
                )}
              >
                {pending.options.cancelLabel ?? t("common.cancel")}
              </button>
              <button
                ref={confirmBtnRef}
                type="button"
                onClick={() => close(true)}
                className={clsx(
                  "inline-flex items-center justify-center h-10 px-4 rounded-control",
                  "text-ui font-medium text-surface transition-colors",
                  pending.options.destructive
                    ? "bg-danger hover:bg-danger/90"
                    : "bg-text-primary hover:bg-text-primary/90",
                )}
              >
                {pending.options.confirmLabel ?? t("confirmDialog.confirm")}
              </button>
            </div>
          </div>
        </Dialog>
      )}
    </ConfirmCtx.Provider>
  );
}
