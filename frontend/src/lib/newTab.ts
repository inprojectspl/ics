/** Opens an app address in a new tab, without giving it a handle on this one. */
export function openInNewTab(href: string): void {
  window.open(href, "_blank", "noopener,noreferrer");
}
