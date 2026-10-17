import type { ReactNode } from "react";
import { clsx } from "clsx";

/**
 * Label and value pairs of a record (a user's profile, an audit event):
 * two columns from `sm`, label over value on phones. `code` sets the values
 * in the monospace face for stored identifiers.
 */
export function DetailList({ children, code = false, className }: { children: ReactNode; code?: boolean; className?: string }) {
  return (
    <dl
      className={clsx(
        "grid gap-x-6 gap-y-2 sm:grid-cols-[9rem_minmax(0,1fr)]",
        code ? "font-code text-meta text-text-secondary" : "text-ui text-text-primary",
        className,
      )}
    >
      {children}
    </dl>
  );
}

export function DetailItem({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="font-ui text-meta text-text-secondary sm:pt-px">{label}</dt>
      <dd className="min-w-0 [overflow-wrap:anywhere] max-sm:-mt-1.5 max-sm:mb-1">{children}</dd>
    </>
  );
}
