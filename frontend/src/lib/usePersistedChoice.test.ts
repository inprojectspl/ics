import { afterEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";

import { usePersistedChoice } from "./usePersistedChoice";

const OPTIONS = ["a", "b"] as const;

afterEach(() => {
  window.localStorage.clear();
  vi.restoreAllMocks();
});

describe("usePersistedChoice", () => {
  it("remembers the choice and reads it back", () => {
    const first = renderHook(() => usePersistedChoice("k", OPTIONS, "a"));
    expect(first.result.current[0]).toBe("a");
    act(() => first.result.current[1]("b"));
    expect(first.result.current[0]).toBe("b");

    const again = renderHook(() => usePersistedChoice("k", OPTIONS, "a"));
    expect(again.result.current[0]).toBe("b");
  });

  it("falls back on an unknown value and on blocked storage", () => {
    window.localStorage.setItem("k", "zzz");
    expect(renderHook(() => usePersistedChoice("k", OPTIONS, "a")).result.current[0]).toBe("a");

    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const { result } = renderHook(() => usePersistedChoice("k", OPTIONS, "b"));
    expect(result.current[0]).toBe("b");
    act(() => result.current[1]("a"));
    expect(result.current[0]).toBe("a");
  });
});
