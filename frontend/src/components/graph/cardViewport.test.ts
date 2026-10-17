import { describe, expect, it } from "vitest";

import {
  CARD_ZOOM,
  FIT_MAX_ZOOM,
  FOCUS_MIN_ZOOM,
  blendTransform,
  centreOn,
  clampZoom,
  fitCards,
  fitScene,
  wheelFactor,
  zoomAt,
} from "./cardViewport";

const SIZE = { w: 1000, h: 600 };

describe("fitScene", () => {
  it("centres the scene and keeps the padding and the bottom strip free", () => {
    const t = fitScene({ width: 2000, height: 500 }, SIZE, 50, CARD_ZOOM, 40);
    expect(t.zoom).toBeCloseTo(0.45);
    expect(t.x).toBeCloseTo(50);
    const bottom = t.y + 500 * t.zoom;
    expect(bottom).toBeLessThanOrEqual(SIZE.h - 50 - 40 + 0.001);
    expect(t.y).toBeGreaterThanOrEqual(50);
  });

  it("clamps the zoom to the range and survives an empty scene", () => {
    expect(fitScene({ width: 10, height: 10 }, SIZE).zoom).toBe(FIT_MAX_ZOOM);
    expect(fitScene({ width: 0, height: 0 }, SIZE)).toEqual({ x: 0, y: 0, zoom: 1 });
    expect(clampZoom(100)).toBe(CARD_ZOOM.max);
    expect(clampZoom(0)).toBe(CARD_ZOOM.min);
  });
});

describe("fitCards", () => {
  const box = (x: number, y: number) => ({ x, y, w: 200, h: 60 });

  it("frames a small neighbourhood at no more than 100%", () => {
    const t = fitCards([box(0, 0), box(300, 200)], SIZE);
    expect(t?.zoom).toBe(1);
    expect(fitCards([], SIZE)).toBeNull();
  });

  it("centres a wide fan on its centre card instead of shrinking it unreadably", () => {
    const cards = Array.from({ length: 30 }, (_, i) => box(i * 250, 0));
    const centre = cards[10];
    const t = fitCards(cards, SIZE, 32, CARD_ZOOM, 0, centre);
    expect(t?.zoom).toBe(FOCUS_MIN_ZOOM);
    const screenX = ((centre?.x ?? 0) + 100) * (t?.zoom ?? 1) + (t?.x ?? 0);
    expect(screenX).toBeCloseTo(SIZE.w / 2);
  });
});

describe("zoomAt and centreOn", () => {
  it("keeps the world point under the anchor in place", () => {
    const t = zoomAt({ x: 10, y: 20, zoom: 1 }, { x: 300, y: 200 }, 2);
    expect(t.zoom).toBe(2);
    expect((300 - t.x) / t.zoom).toBeCloseTo(290);
    expect((200 - t.y) / t.zoom).toBeCloseTo(180);
  });

  it("centres a world point", () => {
    const t = centreOn({ x: 0, y: 0, zoom: 0.5 }, { x: 100, y: 100 }, SIZE);
    expect(100 * t.zoom + t.x).toBe(SIZE.w / 2);
  });
});

describe("wheelFactor", () => {
  it("zooms in on a wheel up, out on a wheel down, pinch steeper, within bounds", () => {
    expect(wheelFactor({ deltaY: -100, deltaMode: 0, ctrlKey: false })).toBeGreaterThan(1);
    expect(wheelFactor({ deltaY: 100, deltaMode: 0, ctrlKey: false })).toBeLessThan(1);
    const pinch = wheelFactor({ deltaY: -10, deltaMode: 0, ctrlKey: true });
    const wheel = wheelFactor({ deltaY: -10, deltaMode: 0, ctrlKey: false });
    expect(pinch).toBeGreaterThan(wheel);
    expect(wheelFactor({ deltaY: -50, deltaMode: 1, ctrlKey: false })).toBeCloseTo(1.6);
    expect(wheelFactor({ deltaY: 5, deltaMode: 2, ctrlKey: false })).toBeCloseTo(1 / 1.6);
  });
});

describe("blendTransform", () => {
  it("starts at the first view and ends at the second", () => {
    const a = { x: 0, y: 0, zoom: 1 };
    const b = { x: -500, y: -200, zoom: 2 };
    expect(blendTransform(a, b, 0, SIZE)).toEqual(a);
    const end = blendTransform(a, b, 1, SIZE);
    expect(end.zoom).toBeCloseTo(2);
    expect(end.x).toBeCloseTo(-500);
    expect(end.y).toBeCloseTo(-200);
    const mid = blendTransform(a, b, 0.5, SIZE);
    expect(mid.zoom).toBeGreaterThan(1);
    expect(mid.zoom).toBeLessThan(2);
  });
});
