import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { api } from "../api";
import { ApiError } from "../api/_core";
import { useEntryFallback } from "./useEntryFallback";

const replace = vi.fn();

beforeEach(() => {
  replace.mockClear();
  // `location.replace` does not work in jsdom, so only that method is swapped;
  // the rest of the object (origin, pathname) stays real.
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...window.location, replace },
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useEntryFallback", () => {
  it("leaves the resolver alone without an error", () => {
    const spy = vi.spyOn(api, "getEntry");
    const { result } = renderHook(() => useEntryFallback("abc123", null));
    expect(result.current).toBe("idle");
    expect(spy).not.toHaveBeenCalled();
  });

  it("ignores errors unrelated to access", () => {
    const spy = vi.spyOn(api, "getEntry");
    const { result } = renderHook(() => useEntryFallback("abc123", 500));
    expect(result.current).toBe("idle");
    expect(spy).not.toHaveBeenCalled();
  });

  it("moves to the share link the resolver points to", async () => {
    vi.spyOn(api, "getEntry").mockResolvedValue({
      action: "redirect",
      url: "https://ics.example/s/tok123",
    });
    renderHook(() => useEntryFallback("abc123", 401));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("https://ics.example/s/tok123"));
  });

  it("sends to login when entry needs an account", async () => {
    vi.spyOn(api, "getEntry").mockResolvedValue({ action: "login", slug: "abc123" });
    renderHook(() => useEntryFallback("abc123", 401));
    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith("/#login?next=%2Fv%2Fabc123"),
    );
  });

  it("does not redirect to where it already is", async () => {
    vi.spyOn(api, "getEntry").mockResolvedValue({
      action: "redirect",
      url: window.location.pathname,
    });
    const { result } = renderHook(() => useEntryFallback("abc123", 401));
    await waitFor(() => expect(result.current).toBe("dead-end"));
    expect(replace).not.toHaveBeenCalled();
  });

  it("ends with a message when the resolver knows no way in", async () => {
    vi.spyOn(api, "getEntry").mockRejectedValue(new ApiError(404, null, "404 Not Found"));
    const { result } = renderHook(() => useEntryFallback("abc123", 404));
    await waitFor(() => expect(result.current).toBe("dead-end"));
    expect(replace).not.toHaveBeenCalled();
  });

  it("does not mistake a rate limit for no access", async () => {
    // A 429 from LINK_ENTRY (shared office IP, a burst of clicks) is an outage,
    // not an access verdict; a "no access" screen would be a lie.
    vi.spyOn(api, "getEntry").mockRejectedValue(
      new ApiError(429, "too many attempts", "too many attempts"),
    );
    const { result } = renderHook(() => useEntryFallback("abc123", 401));
    await waitFor(() => expect(result.current).toBe("unresolved"));
    expect(replace).not.toHaveBeenCalled();
  });

  it("reports `resolving` from the first frame so the reader does not flash an error", () => {
    // The effect runs after render; with an "idle" initial state the reader
    // would paint the error wall before the redirect.
    vi.spyOn(api, "getEntry").mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useEntryFallback("abc123", 404));
    expect(result.current).toBe("resolving");
  });

  it("does not reload the same path when the resolver answers `view`", async () => {
    // The reader got a 401 but the resolver says access exists: the session
    // expired between requests. Redirecting to the same place would loop.
    vi.spyOn(api, "getEntry").mockResolvedValue({ action: "view", slug: "abc123" });
    const { result } = renderHook(() => useEntryFallback("abc123", 401));
    await waitFor(() => expect(result.current).toBe("dead-end"));
    expect(replace).not.toHaveBeenCalled();
  });
});
