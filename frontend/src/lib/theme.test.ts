import { describe, it, expect, beforeEach, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";

type Theme = typeof import("./theme");

let dark = false;
let onSystemChange: (() => void) | null = null;

function stubMedia() {
  vi.spyOn(window, "matchMedia").mockImplementation(
    (query: string) =>
      ({
        get matches() {
          return query.includes("dark") ? dark : false;
        },
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: (_: string, cb: () => void) => {
          onSystemChange = cb;
        },
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }) as unknown as MediaQueryList,
  );
}

// The store is module state; every test gets a fresh module.
async function load(): Promise<Theme> {
  vi.resetModules();
  return import("./theme");
}

beforeEach(() => {
  dark = false;
  onSystemChange = null;
  document.documentElement.removeAttribute("data-theme");
  localStorage.clear();
  stubMedia();
});

describe("readPreference", () => {
  it("returns system without a stored value and ignores garbage", async () => {
    const m = await load();
    expect(m.readPreference()).toBe("system");
    localStorage.setItem("ics-theme", "blue");
    expect(m.readPreference()).toBe("system");
    localStorage.setItem("ics-theme", "dark");
    expect(m.readPreference()).toBe("dark");
  });

  it("treats a blocked localStorage as system", async () => {
    const m = await load();
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(m.readPreference()).toBe("system");
  });
});

describe("getInitialTheme", () => {
  it("takes the data-theme set before start", async () => {
    document.documentElement.setAttribute("data-theme", "dark");
    const m = await load();
    expect(m.getInitialTheme()).toBe("dark");
  });

  it("asks the system without data-theme", async () => {
    dark = true;
    const m = await load();
    expect(m.getInitialTheme()).toBe("dark");
  });
});

describe("setThemePreference", () => {
  it("stores the choice and sets data-theme", async () => {
    const m = await load();
    m.setThemePreference("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(localStorage.getItem("ics-theme")).toBe("dark");
    m.applyTheme("light");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });

  it("resolves system to the system theme", async () => {
    dark = true;
    const m = await load();
    m.setThemePreference("system");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(localStorage.getItem("ics-theme")).toBe("system");
  });

  it("does not abort the change on a localStorage exception", async () => {
    const m = await load();
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceeded");
    });
    expect(() => m.setThemePreference("dark")).not.toThrow();
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });
});

describe("useTheme / useThemePreference", () => {
  it("gives every component the same theme", async () => {
    const m = await load();
    const a = renderHook(() => m.useTheme());
    const b = renderHook(() => m.useThemePreference());
    expect(a.result.current).toBe("light");
    expect(b.result.current[0]).toBe("system");
    act(() => b.result.current[1]("dark"));
    expect(a.result.current).toBe("dark");
    expect(b.result.current[0]).toBe("dark");
  });

  it("follows a system change under the system preference", async () => {
    const m = await load();
    const { result } = renderHook(() => m.useTheme());
    act(() => m.setThemePreference("system"));
    expect(result.current).toBe("light");
    dark = true;
    act(() => onSystemChange?.());
    expect(result.current).toBe("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("ignores a system change under an explicit choice", async () => {
    const m = await load();
    const { result } = renderHook(() => m.useTheme());
    act(() => m.setThemePreference("light"));
    dark = true;
    act(() => onSystemChange?.());
    expect(result.current).toBe("light");
  });
});
