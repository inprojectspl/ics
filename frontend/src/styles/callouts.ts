/**
 * Callout taxonomy - single source of truth for type -> icon-name -> tailwind
 * colorway. Imported by hydrateMarkdown, mountWidgets, and markdown-theme.
 */

const CALLOUT_TYPES = [
  "note", "info", "tip", "success", "question",
  "warning", "failure", "danger", "bug", "example", "quote",
] as const;

export type CalloutType = (typeof CALLOUT_TYPES)[number];

export const CALLOUT_ICON: Record<CalloutType, string> = {
  note: "pencil",
  info: "info",
  tip: "lightbulb",
  success: "check-circle-2",
  question: "help-circle",
  warning: "alert-triangle",
  failure: "x-circle",
  danger: "zap",
  bug: "bug",
  example: "list",
  quote: "quote",
};

export function isCalloutType(s: string): s is CalloutType {
  return (CALLOUT_TYPES as readonly string[]).includes(s);
}
