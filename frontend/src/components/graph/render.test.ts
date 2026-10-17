import { describe, expect, it, vi } from "vitest";

import { PALETTE_FALLBACK, drawScene, hoverFocus, shouldShowLabel } from "./render";
import type { RenderSettings, SimEdge, SimNode } from "./types";

const SETTINGS: RenderSettings = { nodeScale: 1, labels: "hover", showArrows: true };

function node(id: string, x: number, extra: Partial<SimNode> = {}): SimNode {
  return { id, label: id, x, y: 0, vx: 0, vy: 0, pinned: false, degree: 1, ...extra };
}

/** Records the canvas calls drawScene makes; no DOM needed. */
function fakeCanvas() {
  const calls: Array<{ op: string; args: unknown[]; fill?: unknown; alpha?: number }> = [];
  const ctx: Record<string, unknown> = { globalAlpha: 1, fillStyle: "", strokeStyle: "" };
  for (const op of [
    "clearRect", "save", "restore", "translate", "scale", "beginPath", "moveTo",
    "lineTo", "stroke", "arc", "fill", "closePath", "fillText", "setLineDash",
  ]) {
    ctx[op] = vi.fn((...args: unknown[]) => {
      calls.push({ op, args, fill: ctx.fillStyle, alpha: ctx.globalAlpha as number });
    });
  }
  const canvas = { getContext: () => ctx } as unknown as HTMLCanvasElement;
  return { canvas, calls };
}

function draw(nodes: SimNode[], edges: SimEdge[], hoverIdx: number | null, currentId?: string) {
  const { canvas, calls } = fakeCanvas();
  drawScene({
    canvas,
    nodes,
    edges,
    size: { w: 100, h: 100 },
    transform: { x: 0, y: 0, zoom: 1 },
    settings: SETTINGS,
    hoverIdx,
    currentId,
    palette: PALETTE_FALLBACK,
  });
  return calls;
}

describe("hoverFocus", () => {
  it("collects incident edges and their endpoints", () => {
    const edges = [
      { fromIdx: 0, toIdx: 1 },
      { fromIdx: 2, toIdx: 3 },
      { fromIdx: 4, toIdx: 0 },
    ];
    const f = hoverFocus(edges, 0);
    expect([...f.edges]).toEqual([0, 2]);
    expect([...f.nodes].sort()).toEqual([0, 1, 4]);
    expect(hoverFocus(edges, null).edges.size).toBe(0);
  });
});

describe("shouldShowLabel", () => {
  const base = { isHover: false, isCurrent: false, isNbr: false, anyHover: false };

  it("off shows only the current node", () => {
    expect(shouldShowLabel("off", 2, base)).toBe(false);
    expect(shouldShowLabel("off", 2, { ...base, isCurrent: true })).toBe(true);
  });

  it("always depends on zoom only", () => {
    expect(shouldShowLabel("always", 0.7, base)).toBe(true);
    expect(shouldShowLabel("always", 0.5, { ...base, isHover: true })).toBe(false);
  });

  it("hover shows hovered, current, and neighbours when zoomed in", () => {
    expect(shouldShowLabel("hover", 0.5, { ...base, isHover: true })).toBe(true);
    expect(shouldShowLabel("hover", 0.5, { ...base, anyHover: true, isNbr: true })).toBe(false);
    expect(shouldShowLabel("hover", 1, { ...base, anyHover: true, isNbr: true })).toBe(true);
    expect(shouldShowLabel("hover", 1, { ...base, anyHover: true })).toBe(false);
    expect(shouldShowLabel("hover", 1, base)).toBe(true);
  });
});

describe("drawScene", () => {
  it("fills the current node with the accent colour", () => {
    const calls = draw([node("a", 0), node("b", 50)], [], null, "b");
    const fills = calls.filter((c) => c.op === "fill").map((c) => c.fill);
    expect(fills).toEqual([PALETTE_FALLBACK.inkSoft, PALETTE_FALLBACK.accent]);
  });

  it("applies node styles: colour, faded, highlighted, dashed", () => {
    const calls = draw(
      [
        node("a", 0, { style: { color: "#123456", faded: true, dashed: true } }),
        node("b", 50, { style: { highlighted: true } }),
      ],
      [],
      null,
    );
    const fills = calls.filter((c) => c.op === "fill");
    expect(fills[0]).toMatchObject({ fill: "#123456", alpha: 0.3 });
    expect(fills[1]?.fill).toBe(PALETTE_FALLBACK.accent);
    expect(calls.some((c) => c.op === "setLineDash" && (c.args[0] as number[]).length > 0)).toBe(
      true,
    );
    expect(calls.filter((c) => c.op === "fillText").map((c) => c.args[0])).toContain("b");
  });

  it("draws unstyled graphs without dashes", () => {
    const calls = draw([node("a", 0), node("b", 50)], [{ fromIdx: 0, toIdx: 1 }], 0);
    expect(calls.some((c) => c.op === "setLineDash")).toBe(false);
    // Arrowhead drawn in the accent colour for the hovered node's edge.
    const arrow = calls.find((c) => c.op === "fill" && c.fill === PALETTE_FALLBACK.accent);
    expect(arrow).toBeDefined();
  });

  it("skips edges to missing nodes and survives a missing context", () => {
    expect(() => draw([node("a", 0)], [{ fromIdx: 0, toIdx: 9 }], null)).not.toThrow();
    const canvas = { getContext: () => null } as unknown as HTMLCanvasElement;
    expect(() =>
      drawScene({
        canvas,
        nodes: [],
        edges: [],
        size: { w: 1, h: 1 },
        transform: { x: 0, y: 0, zoom: 1 },
        settings: SETTINGS,
        hoverIdx: null,
        currentId: undefined,
      }),
    ).not.toThrow();
  });
});
