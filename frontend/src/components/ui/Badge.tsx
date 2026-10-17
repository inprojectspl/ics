import type { ReactNode } from "react";
import { clsx } from "clsx";

export type BadgeTone = "neutral" | "accent" | "success" | "warning" | "danger";

const TONES: Record<BadgeTone, string> = {
  neutral: "bg-surface-subtle text-text-secondary ring-border",
  accent: "bg-accent-soft text-accent ring-accent/20",
  success: "bg-success-soft text-success ring-success/20",
  warning: "bg-warning-soft text-warning ring-warning/25",
  danger: "bg-danger-soft text-danger ring-danger/20",
};

interface Props {
  tone?: BadgeTone;
  /** A state is told by its words and icon, never by colour alone. */
  icon?: ReactNode;
  title?: string;
  className?: string;
  children: ReactNode;
}

export function Badge({ tone = "neutral", icon, title, className, children }: Props) {
  return (
    <span
      title={title}
      className={clsx(
        "inline-flex h-5 max-w-full shrink-0 items-center gap-1 rounded-full px-2 text-caption font-medium ring-1 ring-inset",
        TONES[tone],
        className,
      )}
    >
      {icon}
      <span className="truncate">{children}</span>
    </span>
  );
}
