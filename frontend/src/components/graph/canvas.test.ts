import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";

import { sizeCanvas, toScreen, useCanvasSize, useFrame, usePalette, useRenderLoop } from "./canvas";

let frames: FrameRequestCallback[] = [];

function flushFrame(): void {
  const pending = frames;
  frames = [];
  for (const cb of pending) cb(0);
}

beforeEach(() => {
  frames = [];
  vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => {
    frames.push(cb);
    return frames.length;
  });
  vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => {
    frames = [];
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  document.documentElement.removeAttribute("data-theme");
});

describe("sizeCanvas", () => {
  it("scales the backing store by devicePixelRatio and keeps CSS size", () => {
    vi.spyOn(window, "devicePixelRatio", "get").mockReturnValue(2);
    const canvas = document.createElement("canvas");
    const setTransform = vi.fn();
    vi.spyOn(canvas, "getContext").mockReturnValue({ setTransform } as unknown as CanvasRenderingContext2D);
    sizeCanvas(canvas, { w: 100, h: 50 });
    expect([canvas.width, canvas.height]).toEqual([200, 100]);
    expect(canvas.style.width).toBe("100px");
    expect(setTransform).toHaveBeenCalledWith(2, 0, 0, 2, 0, 0);
  });
});

describe("toScreen", () => {
  it("subtracts the canvas offset and survives a missing canvas", () => {
    const canvas = document.createElement("canvas");
    vi.spyOn(canvas, "getBoundingClientRect").mockReturnValue({ left: 10, top: 20 } as DOMRect);
    expect(toScreen(canvas, { clientX: 15, clientY: 25 })).toEqual({ x: 5, y: 5 });
    expect(toScreen(null, { clientX: 15, clientY: 25 })).toEqual({ x: 0, y: 0 });
  });
});

describe("useRenderLoop and useFrame", () => {
  it("runs while the frame asks for more, then idles until invalidated", () => {
    let wanted = 2;
    const frame = vi.fn(() => --wanted > 0);
    const { result, unmount } = renderHook(() => {
      const loop = useRenderLoop();
      useFrame(loop, frame);
      return loop.invalidate;
    });
    flushFrame();
    flushFrame();
    flushFrame();
    expect(frame).toHaveBeenCalledTimes(2);
    expect(frames).toHaveLength(0);

    // Several invalidations before the next frame draw once.
    act(() => {
      result.current();
      result.current();
    });
    expect(frames).toHaveLength(1);
    flushFrame();
    expect(frame).toHaveBeenCalledTimes(3);

    act(() => result.current());
    unmount();
    expect(frames).toHaveLength(0);
  });
});

describe("usePalette", () => {
  it("re-reads the palette and notifies on a theme switch", async () => {
    const onChange = vi.fn();
    const { result } = renderHook(() => usePalette(onChange));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(result.current.current.accent).toBeTruthy();
    document.documentElement.setAttribute("data-theme", "dark");
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(2));
  });
});

describe("useCanvasSize", () => {
  it("resizes the canvas to its wrapper and reports the size", () => {
    let fire: () => void = () => {};
    const observe = vi.fn();
    const disconnect = vi.fn();
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor(cb: () => void) {
          fire = cb;
        }
        observe = observe;
        disconnect = disconnect;
      },
    );
    const wrap = document.createElement("div");
    vi.spyOn(wrap, "getBoundingClientRect").mockReturnValue({ width: 300, height: 200 } as DOMRect);
    const canvas = document.createElement("canvas");
    vi.spyOn(canvas, "getContext").mockReturnValue(null);
    const onResize = vi.fn();
    const wrapRef = { current: wrap };
    const canvasRef = { current: canvas };
    const { result, unmount } = renderHook(() => useCanvasSize(wrapRef, canvasRef, { w: 1, h: 1 }, onResize));
    expect(observe).toHaveBeenCalledWith(wrap);
    act(() => fire());
    expect(result.current.current).toEqual({ w: 300, h: 200 });
    expect(onResize).toHaveBeenCalledWith({ w: 300, h: 200 });
    unmount();
    expect(disconnect).toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});
