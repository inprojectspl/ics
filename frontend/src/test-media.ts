import { vi } from "vitest";
import { resetMediaQueryCache } from "./lib/useMediaQuery";

interface MediaOpts {
  width?: number;
  reducedMotion?: boolean;
  dark?: boolean;
}

/** Stubs `matchMedia` with answers derived from a viewport width and
 * preferences, so layout hooks see a desktop, tablet or phone. */
export function mockMedia({ width = 1440, reducedMotion = false, dark = false }: MediaOpts = {}) {
  resetMediaQueryCache();
  const evaluate = (raw: string): boolean => {
    const query = String(raw ?? "");
    let ok = true;
    for (const m of query.matchAll(/\((min|max)-width:\s*([\d.]+)px\)/g)) {
      const n = Number(m[2]);
      ok = ok && (m[1] === "min" ? width >= n : width <= n);
    }
    if (query.includes("prefers-reduced-motion")) ok = reducedMotion;
    if (query.includes("prefers-color-scheme: dark")) ok = dark;
    return ok;
  };
  return vi.spyOn(window, "matchMedia").mockImplementation(
    (query: string) =>
      ({
        matches: evaluate(query),
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }) as unknown as MediaQueryList,
  );
}
