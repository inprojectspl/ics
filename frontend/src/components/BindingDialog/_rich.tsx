import { Fragment, type ReactNode } from "react";

/** Splits a translated string on `{name}` placeholders and puts the matching
 * node in each slot, so copy with inline code or emphasis stays one
 * catalogue entry instead of fragments glued around JSX. */
export function fill(text: string, nodes: Readonly<Record<string, ReactNode>>): ReactNode {
  const parts = text.split(/\{(\w+)\}/);
  return parts.map((part, i) =>
    // Odd indices are the captured placeholder names.
    i % 2 === 1 ? <Fragment key={i}>{nodes[part] ?? `{${part}}`}</Fragment> : part,
  );
}
