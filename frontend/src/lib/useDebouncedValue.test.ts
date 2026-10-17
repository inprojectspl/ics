import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useDebouncedValue } from "./useDebouncedValue";

describe("useDebouncedValue", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns the initial value immediately", () => {
    const { result } = renderHook(() => useDebouncedValue("a", 250));
    expect(result.current).toBe("a");
  });

  it("returns the new value only after the delay", () => {
    const { result, rerender } = renderHook(({ v }) => useDebouncedValue(v, 250), {
      initialProps: { v: "a" },
    });

    rerender({ v: "ab" });
    expect(result.current).toBe("a");

    act(() => {
      vi.advanceTimersByTime(249);
    });
    expect(result.current).toBe("a");

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(result.current).toBe("ab");
  });

  it("gives one update for fast changes, not one per keystroke", () => {
    const { result, rerender } = renderHook(({ v }) => useDebouncedValue(v, 250), {
      initialProps: { v: "" },
    });

    for (const v of ["a", "ab", "abc", "abcd"]) {
      rerender({ v });
      act(() => {
        vi.advanceTimersByTime(100);
      });
    }
    expect(result.current).toBe("");

    act(() => {
      vi.advanceTimersByTime(250);
    });
    expect(result.current).toBe("abcd");
  });

  it("clears the pending timer on unmount", () => {
    const clear = vi.spyOn(window, "clearTimeout");
    const { unmount, rerender } = renderHook(({ v }) => useDebouncedValue(v, 250), {
      initialProps: { v: "a" },
    });

    rerender({ v: "ab" });
    unmount();

    expect(clear).toHaveBeenCalled();
    // Nothing may run after teardown - a stray callback would set state
    // on an unmounted hook.
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(vi.getTimerCount()).toBe(0);
  });
});
