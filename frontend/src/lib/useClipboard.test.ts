import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useClipboard } from "./useClipboard";

// Long enough that a slow CI runner never clears the key before the check;
// the clearing itself is covered with fake timers below.
const HOLD_MS = 10_000;

describe("useClipboard", () => {
  beforeEach(() => {
    // Fresh mock per test; jsdom has no native `navigator.clipboard`.
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
  });

  it("copies the text to the clipboard and sets copiedKey", async () => {
    const { result } = renderHook(() => useClipboard(HOLD_MS));
    expect(result.current.copiedKey).toBeNull();

    await act(async () => {
      await result.current.copy("hello");
    });
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("hello");
    expect(result.current.copiedKey).toBe("hello");
  });

  it("clears copiedKey after holdMs", async () => {
    vi.useFakeTimers();
    try {
      const { result } = renderHook(() => useClipboard(500));
      await act(async () => {
        await result.current.copy("x");
      });
      expect(result.current.copiedKey).toBe("x");
      act(() => {
        vi.advanceTimersByTime(600);
      });
      expect(result.current.copiedKey).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("leaves no live timer after an unmount before holdMs", async () => {
    // The copy button often sits in a dialog that closes right after the
    // click. Without cleanup the callback would fire in an unmounted tree
    // (`window is not defined` after test teardown).
    vi.useFakeTimers();
    try {
      const { result, unmount } = renderHook(() => useClipboard(500));
      await act(async () => {
        await result.current.copy("x");
      });
      unmount();
      expect(vi.getTimerCount()).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it("uses the explicit key when given", async () => {
    const { result } = renderHook(() => useClipboard(HOLD_MS));
    await act(async () => {
      await result.current.copy("https://very/long", "share-link-1");
    });
    expect(result.current.copiedKey).toBe("share-link-1");
  });

  it("does not crash when the clipboard throws (e.g. no permission)", async () => {
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
    });
    const { result } = renderHook(() => useClipboard(100));
    await act(async () => {
      await result.current.copy("x");
    });
    // No crash, and copiedKey stays null because a failed copy does not set it.
    expect(result.current.copiedKey).toBeNull();
  });
});
