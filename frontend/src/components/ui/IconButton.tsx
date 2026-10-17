import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { clsx } from "clsx";
import type { Side } from "./floating";
import { useTooltip } from "./Tooltip";

type Variant = "ghost" | "subtle" | "secondary";
type Size = "sm" | "md";

const VARIANTS: Record<Variant, string> = {
  ghost: "text-text-secondary hover:text-text-primary hover:bg-surface-hover",
  subtle: "text-text-secondary bg-surface-subtle hover:text-text-primary hover:bg-surface-hover",
  secondary:
    "text-text-secondary bg-surface border border-border-strong hover:text-text-primary hover:bg-surface-hover shadow-card",
};

const SIZES: Record<Size, string> = {
  sm: "size-8",
  md: "size-9",
};

/** Class string of the icon button look, for anchors. */
export function iconButtonClass(variant: Variant = "ghost", size: Size = "md"): string {
  return clsx(
    "relative inline-flex shrink-0 items-center justify-center rounded-control",
    "transition-[background-color,color] duration-150 ease-standard",
    "disabled:opacity-40 disabled:pointer-events-none",
    // 44 px hit area on touch screens around a smaller glyph.
    "after:absolute after:left-1/2 after:top-1/2 after:size-11 after:-translate-1/2 [@media(pointer:fine)]:after:hidden",
    VARIANTS[variant],
    SIZES[size],
  );
}

interface Props extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "aria-label" | "children"> {
  /** Accessible name; also shown as the tooltip. Required: an icon alone names nothing. */
  label: string;
  icon: ReactNode;
  variant?: Variant;
  size?: Size;
  tooltipSide?: Side;
  /** Skip the tooltip where a visible label already sits next to the icon. */
  noTooltip?: boolean;
}

export const IconButton = forwardRef<HTMLButtonElement, Props>(function IconButton(
  { label, icon, variant = "ghost", size = "md", tooltipSide = "bottom", noTooltip, className, type = "button", ...rest },
  ref,
) {
  const tip = useTooltip(label, { side: tooltipSide });
  return (
    <>
      <button
        ref={ref}
        type={type}
        aria-label={label}
        className={clsx(iconButtonClass(variant, size), className)}
        {...(noTooltip ? {} : tip.triggerProps)}
        {...rest}
      >
        {icon}
      </button>
      {!noTooltip && tip.bubble}
    </>
  );
});
