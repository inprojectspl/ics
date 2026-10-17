import {
  createContext,
  useCallback,
  useContext,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { clsx } from "clsx";
import { CheckCircle2, AlertCircle, Info, X } from "lucide-react";
import { formatApiError } from "../lib/apiError";
import { t } from "../lib/i18n";

type ToastKind = "success" | "error" | "info";

interface ToastItem {
  id: number;
  kind: ToastKind;
  message: string;
  /** Stage drives the slide+fade animation. "enter" -> "shown" -> "exit". */
  stage: "enter" | "shown" | "exit";
}

interface ToastContextValue {
  toast: (message: string, kind?: ToastKind) => void;
}

const ToastCtx = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const v = useContext(ToastCtx);
  if (!v) {
    throw new Error("useToast() must be used inside <ToastProvider>");
  }
  return v;
}

/** Stable callback that shows an API error as an error toast. */
export function useErrorToast(): (err: unknown) => void {
  const { toast } = useToast();
  return useCallback((err: unknown) => toast(formatApiError(err), "error"), [toast]);
}

const TTL_MS = 3500;
const EXIT_MS = 180;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const idRef = useRef(0);

  const dismiss = useCallback((id: number) => {
    setItems((prev) => prev.map((t) => (t.id === id ? { ...t, stage: "exit" } : t)));
    window.setTimeout(() => {
      setItems((prev) => prev.filter((t) => t.id !== id));
    }, EXIT_MS);
  }, []);

  const toast = useCallback<ToastContextValue["toast"]>(
    (message, kind = "info") => {
      const id = ++idRef.current;
      setItems((prev) => [...prev, { id, kind, message, stage: "enter" }]);
      // Next frame: flip stage to "shown" so the CSS transition kicks in.
      requestAnimationFrame(() => {
        setItems((prev) =>
          prev.map((t) => (t.id === id ? { ...t, stage: "shown" } : t)),
        );
      });
      window.setTimeout(() => dismiss(id), TTL_MS);
    },
    [dismiss],
  );

  return (
    <ToastCtx.Provider value={{ toast }}>
      {children}
      <div
        aria-live="polite"
        aria-atomic="false"
        className="fixed bottom-6 right-6 z-50 flex flex-col gap-2 pointer-events-none"
      >
        {items.map((t) => (
          <ToastCard key={t.id} item={t} onDismiss={() => dismiss(t.id)} />
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

function ToastCard({
  item,
  onDismiss,
}: {
  item: ToastItem;
  onDismiss: () => void;
}) {
  const { kind, message, stage } = item;
  const Icon = kind === "success" ? CheckCircle2 : kind === "error" ? AlertCircle : Info;

  // Only the icon chip is tinted; the icon shape repeats the signal for
  // users who cannot perceive hue.
  const tint =
    kind === "success"
      ? "bg-accent/12 text-accent"
      : kind === "error"
        ? "bg-danger/12 text-danger"
        : "bg-text-primary/[0.06] text-text-secondary";

  return (
    <div
      role={kind === "error" ? "alert" : "status"}
      className={clsx(
        "pointer-events-auto flex items-start gap-3 min-w-[18rem] max-w-md",
        "rounded-card border border-border bg-surface/95 backdrop-blur-md",
        "shadow-floating",
        "pl-3 pr-3 py-2.5",
        "transition-colors duration-200 ease-standard",
        stage === "enter" && "opacity-0 translate-y-2 scale-[0.98]",
        stage === "shown" && "opacity-100 translate-y-0 scale-100",
        stage === "exit" && "opacity-0 translate-y-2 scale-[0.98] duration-150",
      )}
    >
      <span
        aria-hidden
        className={clsx("grid place-items-center size-7 rounded-full shrink-0", tint)}
      >
        <Icon size={16} />
      </span>
      <p className="text-ui text-text-primary leading-snug flex-1 min-w-0">
        {message}
      </p>
      <button
        type="button"
        onClick={onDismiss}
        aria-label={t("toast.dismiss")}
        className="shrink-0 -mr-1 p-1 rounded-control text-text-tertiary hover:text-text-primary hover:bg-surface-subtle/60 transition-colors"
      >
        <X size={14} aria-hidden />
      </button>
    </div>
  );
}
