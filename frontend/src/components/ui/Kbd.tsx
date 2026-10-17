import type { ReactNode } from "react";

/** A key as printed on the keyboard, in shortcut hints. */
export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="inline-flex h-5 min-w-5 items-center justify-center rounded-xs border border-border bg-surface-subtle px-1 font-code text-caption text-text-secondary">
      {children}
    </kbd>
  );
}
