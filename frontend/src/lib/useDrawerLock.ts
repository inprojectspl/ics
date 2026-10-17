import { useEffect } from "react";

interface Options {
  /** Only engage the lock+Esc handler below the `lg` breakpoint. Useful
   * for components that render as a push-column on desktop but as an
   * overlay drawer on mobile - the desktop variant doesn't want either
   * the scroll lock or the Esc-to-close behaviour. */
  mobileOnly?: boolean;
}

const MOBILE_BELOW = "(max-width: 1023.98px)";

/**
 * Body scroll lock + Esc-to-close for off-canvas drawers. Hooks the
 * `<body>` class instead of inline styles so other lockers (e.g. Modal)
 * compose with us - multiple components add the class, removal is
 * idempotent. Cleanup always runs on unmount even with `open=true`.
 */
export function useDrawerLock(
  open: boolean,
  onClose: () => void,
  options: Options = {},
): void {
  const { mobileOnly = false } = options;
  useEffect(() => {
    if (!open) return;
    if (mobileOnly && !window.matchMedia(MOBILE_BELOW).matches) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.body.classList.add("overflow-hidden");
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.classList.remove("overflow-hidden");
      window.removeEventListener("keydown", onKey);
    };
  }, [open, onClose, mobileOnly]);
}
