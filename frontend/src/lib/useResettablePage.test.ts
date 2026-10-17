import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useResettablePage } from "./useResettablePage";

describe("useResettablePage", () => {
  it("keeps the chosen page while the key stays the same", () => {
    const { result, rerender } = renderHook(({ k }) => useResettablePage(k), {
      initialProps: { k: "a" },
    });
    act(() => result.current[1](3));
    act(() => result.current[1]((p) => p + 1));
    rerender({ k: "a" });
    expect(result.current[0]).toBe(4);
  });

  it("goes back to page 1 when the key changes", () => {
    const { result, rerender } = renderHook(({ k }) => useResettablePage(k), {
      initialProps: { k: "a" },
    });
    act(() => result.current[1](3));
    rerender({ k: "b" });
    expect(result.current[0]).toBe(1);
    act(() => result.current[1]((p) => p + 1));
    expect(result.current[0]).toBe(2);
  });
});
