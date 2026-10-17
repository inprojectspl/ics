import { useCallback, useEffect, useRef, useState } from "react";

/**
 * `copy(text, key)` writes to the clipboard and marks `key` as just copied
 * for `holdMs`. The reset timer is cleared on unmount because copy buttons
 * often sit in dialogs that close right after the click.
 */
export function useClipboard(holdMs = 1500): {
  copy: (text: string, key?: string) => Promise<void>;
  copiedKey: string | null;
} {
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timer.current !== null) clearTimeout(timer.current);
    },
    [],
  );

  const copy = useCallback(
    async (text: string, key: string = text) => {
      try {
        await navigator.clipboard.writeText(text);
        setCopiedKey(key);
        // Copying two things in quick succession: the older timer would clear
        // the newer label before `holdMs` has passed.
        if (timer.current !== null) clearTimeout(timer.current);
        timer.current = setTimeout(() => {
          timer.current = null;
          setCopiedKey((cur) => (cur === key ? null : cur));
        }, holdMs);
      } catch {
        /* ignore - fall back to manual select */
      }
    },
    [holdMs],
  );

  return { copy, copiedKey };
}
