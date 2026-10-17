// Unread count in the tab title ("(3) ICS") and on the installed app icon.
import { setTitlePrefix } from "../documentTitle";

export function badgeLabel(count: number): string {
  return count > 99 ? "99+" : String(count);
}

export function setTitleCount(count: number): void {
  setTitlePrefix(count > 0 ? `(${badgeLabel(count)}) ` : "");
}

interface BadgeNavigator {
  setAppBadge?: (count?: number) => Promise<void>;
  clearAppBadge?: () => Promise<void>;
}

/** Badging API of an installed app; a no-op elsewhere. */
export function setAppBadge(count: number): void {
  const nav = navigator as unknown as BadgeNavigator;
  try {
    const pending = count > 0 ? nav.setAppBadge?.(count) : nav.clearAppBadge?.();
    pending?.catch(() => undefined);
  } catch {
    /* not allowed in this context */
  }
}
