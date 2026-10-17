import { describe, expect, it } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { setStreamLive, useStreamLive } from "./liveState";

describe("useStreamLive", () => {
  it("follows the stream state", () => {
    const { result } = renderHook(() => useStreamLive());
    expect(result.current).toBe(false);
    act(() => setStreamLive(true));
    expect(result.current).toBe(true);
    act(() => setStreamLive(false));
    expect(result.current).toBe(false);
  });
});
