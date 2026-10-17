import "@testing-library/jest-dom/vitest";
import { configure } from "@testing-library/react";
import { afterEach, vi } from "vitest";
import { resetMediaQueryCache } from "./lib/useMediaQuery";
import { setLocale } from "./lib/i18n";

// The default 1 s for findBy/waitFor is too tight on a busy shared CI runner:
// a first render that takes 100 ms locally timed out there.
configure({ asyncUtilTimeout: 5000 });
// The per-test budget must exceed one async util: with both at 5 s, a single
// slow waitFor failed the whole test. Tests that render long lists took 5-10 s
// on the CI runner under coverage and 0.3 s locally.
vi.setConfig({ testTimeout: 20_000 });

// Node >= 22 exposes its own global `localStorage` (webstorage), which is
// `undefined` without the `--localstorage-file` flag, and vitest does not
// replace an existing global with the jsdom one (in vitest `window` ===
// `globalThis`, so the jsdom implementation cannot be recovered from here).
// Without this, tests fail on `localStorage.clear()` on the host (Node 26)
// while passing in the container (Node 20). Stub a full in-memory Storage,
// the same pattern as matchMedia below.
if (globalThis.localStorage == null) {
  const store = new Map<string, string>();
  const memoryStorage: Storage = {
    get length() {
      return store.size;
    },
    clear: () => store.clear(),
    getItem: (key: string) => store.get(key) ?? null,
    key: (index: number) => [...store.keys()][index] ?? null,
    removeItem: (key: string) => void store.delete(key),
    setItem: (key: string, value: string) => void store.set(key, String(value)),
  };
  Object.defineProperty(globalThis, "localStorage", {
    value: memoryStorage,
    configurable: true,
  });
}

// jsdom does not implement `window.matchMedia`. Up to vitest 3 the jsdom
// environment shipped a throwing stub (a function, so `vi.spyOn` had something
// to replace); vitest 4 leaves it `undefined`. Stub it as "light"
// (matches:false); tests that need dark override it via `vi.spyOn(window, "matchMedia")`.
if (!window.matchMedia) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

// jsdom has no canvas and logs "Not implemented" for every getContext call
// (the sign-in backdrop mounts on each pre-auth screen). Tests that draw
// replace it with `vi.spyOn(HTMLCanvasElement.prototype, "getContext")`.
HTMLCanvasElement.prototype.getContext = (() => null) as typeof HTMLCanvasElement.prototype.getContext;

// Tests assert on English copy: pin the locale so they do not depend on the
// runner's browser language, and undo any switch a test made.
setLocale("en", { persist: false });
afterEach(() => setLocale("en", { persist: false }));
// Media query lists are cached per query; a restored `matchMedia` stub must not leak.
afterEach(() => resetMediaQueryCache());
