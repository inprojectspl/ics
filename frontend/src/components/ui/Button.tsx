import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { clsx } from "clsx";
import { Loader2 } from "lucide-react";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "danger-solid";
export type ButtonSize = "sm" | "md" | "lg";

const BASE =
  "relative inline-flex items-center justify-center gap-2 shrink-0 whitespace-nowrap select-none " +
  "rounded-control font-medium transition-[background-color,border-color,color] duration-150 ease-standard " +
  "disabled:opacity-50 disabled:pointer-events-none aria-disabled:opacity-50 " +
  // The visible control may be 32-36 px, but a finger needs 44 px.
  "after:absolute after:inset-x-0 after:top-1/2 after:-translate-y-1/2 after:h-11 after:min-h-full [@media(pointer:fine)]:after:hidden";

const VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-accent text-on-accent hover:bg-accent-hover shadow-card",
  secondary:
    "bg-surface text-text-primary border border-border-strong hover:bg-surface-hover hover:border-border-strong shadow-card",
  ghost: "text-text-secondary hover:text-text-primary hover:bg-surface-hover",
  danger: "text-danger hover:bg-danger-soft",
  "danger-solid": "bg-danger text-surface hover:bg-danger/90",
};

const SIZES: Record<ButtonSize, string> = {
  sm: "h-8 px-3 text-ui",
  md: "h-9 px-3.5 text-ui",
  lg: "h-11 px-5 text-body",
};

/** Class string of the button look, for links that must stay anchors. */
export function buttonClass(variant: ButtonVariant = "primary", size: ButtonSize = "md"): string {
  return clsx(BASE, VARIANTS[variant], SIZES[size]);
}

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Leading icon; replaced by a spinner while `busy`. */
  icon?: ReactNode;
  /** Trailing icon, e.g. the chevron of a split button. */
  trailingIcon?: ReactNode;
  /** In-flight state: keeps the label (no reflow under the pointer) and disables the button. */
  busy?: boolean;
}

/** The one button of the app. One primary per area; the rest are secondary, ghost or a menu. */
export const Button = forwardRef<HTMLButtonElement, Props>(function Button(
  {
    variant = "primary",
    size = "md",
    icon,
    trailingIcon,
    busy = false,
    disabled,
    className,
    type = "button",
    children,
    ...rest
  },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      className={clsx(buttonClass(variant, size), className)}
      {...rest}
    >
      {busy ? <Loader2 size={16} aria-hidden className="animate-spin" /> : icon}
      {children}
      {trailingIcon}
    </button>
  );
});
