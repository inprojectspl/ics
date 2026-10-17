import type { ReactNode } from "react";

/** Text input look without a size or border colour; `inputClass` adds both. */
export const INPUT_BASE =
  "block rounded-control border bg-surface px-3 text-text-primary " +
  "placeholder:text-text-tertiary transition-[border-color,box-shadow] duration-150 ease-standard " +
  "focus:border-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/25 disabled:opacity-60";

const INPUT_HEIGHT = { sm: "h-8", md: "h-9", lg: "h-10" } as const;

/**
 * A text input or select of the form look, one utility per property so no
 * call site has to override a height, width or border (two utilities for
 * one property resolve by stylesheet order, not by their order in
 * `className`). `sm` fits toolbars and setting rows, `lg` the sign-in card.
 */
export function inputClass({
  size = "md",
  full = true,
  invalid = false,
}: { size?: keyof typeof INPUT_HEIGHT; full?: boolean; invalid?: boolean } = {}): string {
  return `${INPUT_BASE} ${INPUT_HEIGHT[size]} ${full ? "w-full" : ""} ${invalid ? "border-danger" : "border-border-strong"} text-ui`;
}

/** The form input look: 36 px high, full width, strong border. */
export const INPUT_CLASS = inputClass();

/** Multi-line variant of `INPUT_CLASS`. */
export const TEXTAREA_CLASS = `${INPUT_BASE} w-full border-border-strong py-2 text-ui leading-relaxed`;

/** Labelled control; the hint sits outside <label> so it is not part of the name. */
export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div>
      <label className="block">
        <span className="mb-1.5 block text-ui font-medium text-text-primary">{label}</span>
        {children}
      </label>
      {hint && <p className="mt-1.5 text-meta text-text-secondary">{hint}</p>}
    </div>
  );
}
