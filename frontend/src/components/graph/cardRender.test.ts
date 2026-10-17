import { describe, expect, it, vi } from "vitest";

import { labelPoint, routeAt, routeMidpoint } from "./cardLabels";
import { drawCardScene, focusOf, hitCard } from "./cardRender";
import { layoutCardScene } from "./cardScene";
import { fitText, wrapLines } from "./cardText";
import type { CardEdge, CardNode, CardScene, Density } from "./cardTypes";
import { drawMinimap, minimapToWorld, MINIMAP_SIZE, wholeSceneInView } from "./minimap";
import { PALETTE_FALLBACK } from "./render";

/** A 2D context that records calls; text is 6 px per character. */
function fakeContext() {
  const calls: string[] = [];
  const texts: string[] = [];
  const ctx: Record<string, unknown> = {
    globalAlpha: 1,
    fillStyle: "",
    strokeStyle: "",
    font: "10px x",
    letterSpacing: "0px",
    measureText: (s: string) => ({ width: s.length * 6 }),
    createPattern: () => ({}),
    fillText: vi.fn((s: string) => texts.push(s)),
  };
  for (const op of [
    "clearRect", "save", "restore", "translate", "scale", "beginPath", "moveTo", "lineTo",
    "bezierCurveTo", "arcTo", "stroke", "fill", "closePath", "setLineDash", "roundRect",
    "clip", "fillRect", "strokeRect", "arc", "drawImage",
  ]) {
    ctx[op] = vi.fn(() => calls.push(op));
  }
  const canvas = { getContext: () => ctx } as unknown as HTMLCanvasElement;
  return { canvas, ctx: ctx as unknown as CanvasRenderingContext2D, calls, texts };
}

const card = (id: string, component: number, over: Partial<CardNode> = {}): CardNode => ({
  id,
  title: `Title of ${id}`,
  kicker: "Spec",
  color: "#123456",
  component,
  ...over,
});
const edge = (source: string, target: string, kind = "derived_from", label = "derived"): CardEdge => ({
  id: `${source}>${target}`,
  source,
  target,
  kind,
  width: 1.5,
  label,
});

function scene(density: Density = "normal"): CardScene {
  return layoutCardScene(
    [
      card("a", 0),
      card("b", 0, { badge: { text: "Review", tone: "warn" }, sub: "Summary" }),
      card("c", 0, { muted: true, badge: { text: "Old", tone: "mute" } }),
      card("d", 0, { dashed: true, badge: { text: "Outside", tone: "info" } }),
      card("t", 0, { variant: "task" }),
      card("x", -1),
    ],
    [edge("b", "a"), edge("c", "a"), edge("d", "b", "relates_to"), edge("t", "b", "task"), edge("c", "b", "contradicts")],
    {
      size: { w: 200, h: 60 },
      density,
      layerKinds: new Set(["derived_from", "task"]),
      frameTitle: () => ({ label: "Group", count: "5 documents" }),
      unlinkedTitle: () => ({ label: "Loose" }),
    },
  );
}

function draw(zoom: number, density: Density, focusId: string | null = null) {
  const f = fakeContext();
  const s = scene(density);
  drawCardScene({
    canvas: f.canvas,
    scene: s,
    size: { w: 800, h: 600 },
    transform: { x: 0, y: 0, zoom },
    palette: PALETTE_FALLBACK,
    hoverId: focusId,
    selectedId: "a",
    focus: focusOf(s, focusId),
    grid: true,
  });
  return f;
}

describe("drawCardScene", () => {
  it("draws full cards close up: kicker, badge, title, the detailed line", () => {
    const { texts } = draw(1, "detailed");
    expect(texts).toContain("SPEC");
    expect(texts).toContain("Review");
    expect(texts).toContain("Summary");
    expect(texts).toContain("Group");
    expect(texts).toContain(" · 5 documents");
  });

  it("draws the title alone at a middle distance and colour tiles far out", () => {
    const middle = draw(0.6, "normal").texts;
    expect(middle.some((t) => t.startsWith("Title"))).toBe(true);
    expect(middle).not.toContain("SPEC");
    const far = draw(0.2, "normal").texts;
    expect(far.some((t) => t.startsWith("Title"))).toBe(false);
  });

  it("labels the relations of the focused card", () => {
    const { texts } = draw(1, "compact", "b");
    expect(draw(0.6, "compact", "b").texts.length).toBeGreaterThan(0);
    expect(texts).toContain("derived");
  });

  it("survives a canvas without a 2D context", () => {
    const canvas = { getContext: () => null } as unknown as HTMLCanvasElement;
    const s = scene();
    expect(() =>
      drawCardScene({
        canvas,
        scene: s,
        size: { w: 10, h: 10 },
        transform: { x: 0, y: 0, zoom: 1 },
        palette: PALETTE_FALLBACK,
        hoverId: null,
        selectedId: null,
        focus: null,
      }),
    ).not.toThrow();
  });
});

describe("focusOf and hitCard", () => {
  it("lights the card, its neighbours and its edges", () => {
    const s = scene();
    const f = focusOf(s, "b");
    expect(f?.centre).toBe("b");
    expect([...(f?.cards ?? [])].sort()).toEqual(["a", "b", "c", "d", "t"]);
    expect(focusOf(s, null)).toBeNull();
  });

  it("finds the card under a point", () => {
    const s = scene();
    const a = s.cards.find((c) => c.id === "a");
    expect(hitCard(s, { x: (a?.x ?? 0) + 5, y: (a?.y ?? 0) + 5 })?.id).toBe("a");
    expect(hitCard(s, { x: -100, y: -100 })).toBeNull();
  });
});

describe("text fitting", () => {
  const { ctx } = fakeContext();

  it("cuts with an ellipsis only when the text does not fit", () => {
    expect(fitText(ctx, "short", 100)).toBe("short");
    const cut = fitText(ctx, "a rather long document title", 60);
    expect(cut.endsWith("…")).toBe(true);
    expect(cut.length * 6).toBeLessThanOrEqual(60);
    expect(fitText(ctx, "anything", 0)).toBe("");
  });

  it("wraps whole words onto two lines", () => {
    expect(wrapLines(ctx, "fits", 100)).toEqual(["fits"]);
    const [first, second] = wrapLines(ctx, "Architecture of the data platform lakehouse", 90);
    expect(first).toBe("Architecture of");
    expect(second?.endsWith("…")).toBe(true);
    expect(wrapLines(ctx, "Supercalifragilistic", 30)).toHaveLength(1);
  });
});

describe("label placement", () => {
  it("walks a route from its source to its target, toward the neighbour of the focused card", () => {
    const flow = { ...edge("a", "b"), shape: "flow" as const, points: [{ x: 0, y: 100 }, { x: 0, y: 0 }] };
    expect(labelPoint(flow, "a", 0.75, true).y).toBeLessThan(50);
    expect(labelPoint(flow, "b", 0.75, true).y).toBeGreaterThan(50);
    const chain = { ...flow, shape: "loop" as const, points: [{ x: 0, y: 200 }, { x: 0, y: 100 }, { x: 100, y: 100 }] };
    expect(routeAt(chain, 0.5, true)).toEqual({ x: 0, y: 100 });
    expect(routeAt(chain, 1, true)).toEqual({ x: 100, y: 100 });
    expect(routeAt({ ...flow, points: [{ x: 0, y: 0 }, { x: 100, y: 10 }] }, 0.5, false).x).toBeCloseTo(50);
    expect(routeAt({ ...flow, points: [] }, 0.5, true)).toEqual({ x: 0, y: 0 });
    expect(routeMidpoint([])).toEqual({ x: 0, y: 0 });
  });

  it("never puts a label over a card or outside the canvas", () => {
    const f = fakeContext();
    const s = scene();
    const boxes: Array<{ x: number; y: number; w: number; h: number }> = [];
    (f.ctx as unknown as { roundRect: (x: number, y: number, w: number, h: number) => void }).roundRect = (x, y, w, h) => {
      if (h === 20) boxes.push({ x, y, w, h });
    };
    drawCardScene({
      canvas: f.canvas,
      scene: s,
      size: { w: 2000, h: 2000 },
      transform: { x: 0, y: 0, zoom: 1 },
      palette: PALETTE_FALLBACK,
      hoverId: "b",
      selectedId: null,
      focus: focusOf(s, "b"),
    });
    expect(boxes.length).toBeGreaterThan(0);
    for (const b of boxes) {
      for (const c of s.cards) {
        const hit = b.x < c.x + c.w && c.x < b.x + b.w && b.y < c.y + c.h && c.y < b.y + b.h;
        expect(hit).toBe(false);
      }
    }
  });
});

describe("minimap", () => {
  it("maps its points back to the world and hides the outline when all is in view", () => {
    const s = scene();
    const centre = minimapToWorld(s, { x: MINIMAP_SIZE.w / 2, y: MINIMAP_SIZE.h / 2 });
    expect(centre.x).toBeCloseTo(s.width / 2);
    expect(centre.y).toBeCloseTo(s.height / 2);
    expect(wholeSceneInView(s, { x: 0, y: 0, zoom: 0.1 }, { w: 800, h: 600 })).toBe(true);
    expect(wholeSceneInView(s, { x: -50, y: -50, zoom: 2 }, { w: 200, h: 100 })).toBe(false);
    const f = fakeContext();
    vi.spyOn(document, "createElement").mockReturnValue(f.canvas);
    drawMinimap(f.canvas, s, { x: -50, y: -50, zoom: 2 }, { w: 200, h: 100 }, PALETTE_FALLBACK);
    expect(f.calls).toContain("drawImage");
    expect(f.calls).toContain("strokeRect");
    drawMinimap(f.canvas, s, { x: -5000, y: -5000, zoom: 2 }, { w: 10, h: 10 }, PALETTE_FALLBACK);
    const none = { getContext: () => null } as unknown as HTMLCanvasElement;
    expect(() => drawMinimap(none, s, { x: 0, y: 0, zoom: 1 }, { w: 1, h: 1 }, PALETTE_FALLBACK)).not.toThrow();
    vi.restoreAllMocks();
  });
});
