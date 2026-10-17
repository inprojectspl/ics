import type { LucideIcon } from "lucide-react";

/**
 * One action, described once and rendered by every surface that offers it:
 * the desktop dropdown, the phone action sheet and inline toolbars. Keeping
 * a single definition is what keeps a row's menu, the reader toolbar and
 * the mobile sheet from drifting apart.
 */
export interface MenuAction {
  key: string;
  label: string;
  /** Leading glyph; entries of one menu either all have one or none do. */
  icon?: LucideIcon;
  onClick: () => void;
  danger?: boolean;
  disabled?: boolean;
  /** Why the action is unavailable; shown next to it, not only on hover. */
  disabledHint?: string;
  /** Radio entry (a sort order, a view mode): `true`/`false` renders the check slot. */
  checked?: boolean;
  /** Starts a new group: a divider and this heading above the entry. */
  heading?: string;
}
