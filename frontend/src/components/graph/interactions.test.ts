import { describe, expect, it } from "vitest";

import {
  MAX_ZOOM,
  MIN_ZOOM,
  createPointerState,
  fitTransform,
  hitTest,
  pointerDown,
  pointerMove,
  pointerUp,
  screenToWorld,
  wheelZoomFactor,
  zoomAround,
} from "./interactions";
import type { SimNode, Transform } from "./types";

function node(id: string, x: number, y: number): SimNode {
  return { id, label: id, x, y, vx: 1, vy: 1, pinned: false, degree: 0 };
}

describe("screenToWorld", () => {
  it("inverts pan and zoom", () => {
    expect(screenToWorld({ x: 30, y: 50 }, { x: 10, y: 10, zoom: 2 })).toEqual({ x: 10, y: 20 });
  });
});

describe("hitTest", () => {
  it("returns the topmost node within the radius", () => {
    const nodes = [node("a", 0, 0), node("b", 2, 0)];
    expect(hitTest(nodes, { x: 1, y: 0 }, 1)).toBe(1);
    expect(hitTest(nodes, { x: -3, y: 0 }, 1)).toBe(0);
    expect(hitTest(nodes, { x: 50, y: 50 }, 1)).toBeNull();
  });
});

describe("pointer state machine", () => {
  it("drags a node with the primary button and releases the pin", () => {
    const nodes = [node("a", 0, 0)];
    const state = createPointerState();
    const t: Transform = { x: 0, y: 0, zoom: 2 };
    expect(pointerDown(state, nodes, 0, 0, { x: 0, y: 0 }, t)).toBe("drag");
    expect(nodes[0]?.pinned).toBe(true);
    expect(pointerMove(state, nodes, { x: 20, y: 40 }, t)).toBe(true);
    expect(nodes[0]).toMatchObject({ x: 10, y: 20, vx: 0, vy: 0 });
    pointerUp(state, nodes);
    expect(nodes[0]?.pinned).toBe(false);
    expect(state.draggingIdx).toBeNull();
  });

  it("pans on empty area or a non-primary button", () => {
    const nodes = [node("a", 0, 0)];
    const state = createPointerState();
    const t: Transform = { x: 5, y: 5, zoom: 1 };
    expect(pointerDown(state, nodes, 0, 1, { x: 100, y: 100 }, t)).toBe("pan");
    expect(nodes[0]?.pinned).toBe(false);
    pointerMove(state, nodes, { x: 110, y: 90 }, t);
    expect(t).toEqual({ x: 15, y: -5, zoom: 1 });
    pointerUp(state, nodes);
    expect(state.panning).toBeNull();
  });

  it("reports an idle move so the caller runs hover detection", () => {
    const t: Transform = { x: 0, y: 0, zoom: 1 };
    expect(pointerMove(createPointerState(), [], { x: 1, y: 1 }, t)).toBe(false);
  });
});

describe("zoomAround", () => {
  it("keeps the anchored world point fixed", () => {
    const t: Transform = { x: 10, y: 20, zoom: 1 };
    const anchor = { x: 200, y: 100 };
    const before = screenToWorld(anchor, t);
    zoomAround(t, anchor, 1.5);
    expect(t.zoom).toBe(1.5);
    const after = screenToWorld(anchor, t);
    expect(after.x).toBeCloseTo(before.x);
    expect(after.y).toBeCloseTo(before.y);
  });

  it("clamps the zoom level", () => {
    const t: Transform = { x: 0, y: 0, zoom: 1 };
    zoomAround(t, { x: 0, y: 0 }, 100);
    expect(t.zoom).toBe(MAX_ZOOM);
    zoomAround(t, { x: 0, y: 0 }, 0.0001);
    expect(t.zoom).toBe(MIN_ZOOM);
  });

  it("maps wheel direction to zoom in and out", () => {
    expect(wheelZoomFactor(-100)).toBeGreaterThan(1);
    expect(wheelZoomFactor(100)).toBeLessThan(1);
  });
});

describe("fitTransform", () => {
  it("resets to identity without nodes", () => {
    expect(fitTransform([], { w: 800, h: 600 })).toEqual({ x: 0, y: 0, zoom: 1 });
  });

  it("centres the bounding box", () => {
    const t = fitTransform([node("a", 0, 0), node("b", 400, 300)], { w: 800, h: 600 });
    expect(t.zoom).toBeCloseTo(1.7);
    expect(200 * t.zoom + t.x).toBeCloseTo(400);
    expect(150 * t.zoom + t.y).toBeCloseTo(300);
  });
});
