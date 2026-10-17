import { describe, expect, it, vi } from "vitest";

import { installPreloadRecovery, PRELOAD_RELOAD_KEY } from "./preloadRecovery";

function memoryStorage() {
  const data = new Map<string, string>();
  return {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
  };
}

describe("installPreloadRecovery", () => {
  it("reloads once on the first failed chunk and not again", () => {
    const target = new EventTarget();
    const storage = memoryStorage();
    const reload = vi.fn();
    installPreloadRecovery(target as unknown as Window, storage, reload);

    const first = new Event("vite:preloadError", { cancelable: true });
    target.dispatchEvent(first);
    expect(reload).toHaveBeenCalledTimes(1);
    expect(first.defaultPrevented).toBe(true);
    expect(storage.getItem(PRELOAD_RELOAD_KEY)).toBe("1");

    const second = new Event("vite:preloadError", { cancelable: true });
    target.dispatchEvent(second);
    expect(reload).toHaveBeenCalledTimes(1);
    expect(second.defaultPrevented).toBe(false);
  });

  it("still reloads when storage throws", () => {
    const target = new EventTarget();
    const reload = vi.fn();
    const broken = {
      getItem: () => {
        throw new Error("denied");
      },
      setItem: () => {},
    };
    installPreloadRecovery(target as unknown as Window, broken, reload);
    target.dispatchEvent(new Event("vite:preloadError", { cancelable: true }));
    expect(reload).toHaveBeenCalledTimes(1);
  });
});
