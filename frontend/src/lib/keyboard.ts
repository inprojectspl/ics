/**
 * Whether a key press belongs to the focused element rather than to page
 * shortcuts: text fields take every key, buttons, links and options take
 * Enter and Space (they activate them).
 */
export function ownsKey(target: EventTarget | null, key: string): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable || target.closest("input, textarea, select")) return true;
  return (key === "Enter" || key === " ") && target.closest("button, a, [role=option], [role=tab]") !== null;
}
