// After a deploy the hashed chunks of the previous build are gone, so a tab
// opened before it fails to load any lazy() route. One reload fetches the new
// index.html; the session flag stops a reload loop if the chunk is truly
// missing.
export const PRELOAD_RELOAD_KEY = "ics:preload-reloaded";

export function installPreloadRecovery(
  target: Pick<Window, "addEventListener">,
  storage: Pick<Storage, "getItem" | "setItem">,
  reload: () => void,
): void {
  target.addEventListener("vite:preloadError", (event) => {
    let alreadyReloaded = false;
    try {
      alreadyReloaded = storage.getItem(PRELOAD_RELOAD_KEY) === "1";
      if (!alreadyReloaded) storage.setItem(PRELOAD_RELOAD_KEY, "1");
    } catch {
      // Storage can be unavailable (private mode); reloading once is still right.
    }
    if (alreadyReloaded) return;
    event.preventDefault();
    reload();
  });
}
