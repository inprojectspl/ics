import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";

import { t } from "../../lib/i18n";
import { CardCanvas } from "./CardCanvas";
import { layoutCardScene } from "./cardScene";
import type { CardNode, CardScene } from "./cardTypes";
import { CARD_ZOOM, fitScene } from "./cardViewport";

let frames: FrameRequestCallback[] = [];
let now = 0;

function flush(times = 1): void {
  for (let i = 0; i < times; i++) {
    const pending = frames;
    frames = [];
    act(() => {
      for (const cb of pending) cb(now);
    });
  }
}

function fakeContext() {
  const ctx: Record<string, unknown> = { measureText: (s: string) => ({ width: s.length * 6 }) };
  return new Proxy(ctx, {
    get: (target, key: string) => (key in target ? target[key] : () => {}),
    set: (target, key: string, value) => {
      target[key] = value;
      return true;
    },
  });
}

beforeEach(() => {
  frames = [];
  now = 0;
  vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => {
    frames.push(cb);
    return frames.length;
  });
  vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => {});
  vi.spyOn(performance, "now").mockImplementation(() => now);
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(
    () => fakeContext() as unknown as CanvasRenderingContext2D,
  );
  HTMLElement.prototype.setPointerCapture = vi.fn();
  // jsdom has no PointerEvent; a MouseEvent carries the coordinates the handlers read.
  if (!("PointerEvent" in window)) {
    Object.defineProperty(window, "PointerEvent", { value: MouseEvent, configurable: true });
  }
});

afterEach(() => vi.restoreAllMocks());

const card = (id: string, component = 0): CardNode => ({ id, title: id, color: "#000", component });

function sceneOf(count: number): CardScene {
  const nodes = Array.from({ length: count }, (_, i) => card(`n${i}`));
  const edges = nodes.slice(1).map((n, i) => ({ id: `e${i}`, source: n.id, target: "n0", kind: "derived_from", width: 1 }));
  return layoutCardScene(nodes, edges, { size: { w: 200, h: 60 }, layerKinds: new Set(["derived_from"]) });
}

/** Screen point of a card's centre under the initial fit (800 x 560 canvas). */
function screenOf(scene: CardScene, id: string) {
  const tr = fitScene(scene, { w: 800, h: 560 }, 32, CARD_ZOOM, 44);
  const c = scene.cards.find((x) => x.id === id);
  if (!c) throw new Error(id);
  return { clientX: (c.x + c.w / 2) * tr.zoom + tr.x, clientY: (c.y + c.h / 2) * tr.zoom + tr.y };
}

describe("CardCanvas", () => {
  it("opens a card in a new tab on Ctrl/Cmd+click or a middle click instead of selecting it", () => {
    const scene = sceneOf(3);
    const onSelect = vi.fn();
    const onOpenNewTab = vi.fn();
    render(<CardCanvas scene={scene} selectedId={null} onSelect={onSelect} onOpenNewTab={onOpenNewTab} label="Graph" />);
    flush();
    const canvas = screen.getByRole("img", { name: "Graph" });
    const at = screenOf(scene, "n1");
    for (const mods of [{ ctrlKey: true }, { metaKey: true }]) {
      fireEvent.pointerDown(canvas, { ...at, ...mods });
      fireEvent.pointerUp(canvas, { ...at, ...mods });
    }
    fireEvent.pointerDown(canvas, { ...at, button: 1 });
    fireEvent.pointerUp(canvas, { ...at, button: 1 });
    fireEvent(canvas, new MouseEvent("auxclick", { ...at, button: 1, bubbles: true }));
    expect(onOpenNewTab.mock.calls).toEqual([["n1"], ["n1"], ["n1"]]);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("fits a small scene at 100% at most, while the wheel may still zoom in further", () => {
    render(<CardCanvas scene={sceneOf(1)} selectedId={null} onSelect={vi.fn()} label="Graph" />);
    flush();
    const level = () => screen.getByLabelText(/%/).textContent;
    expect(level()).toBe("100%");
    const canvas = screen.getByRole("img", { name: "Graph" });
    act(() => {
      canvas.dispatchEvent(new WheelEvent("wheel", { deltaY: -200, clientX: 100, clientY: 100, bubbles: true, cancelable: true }));
    });
    flush();
    expect(Number.parseInt(level() ?? "0", 10)).toBeGreaterThan(100);
  });

  it("selects the card under a click and clears on a click on empty canvas", () => {
    const scene = sceneOf(3);
    const onSelect = vi.fn();
    render(<CardCanvas scene={scene} selectedId={null} onSelect={onSelect} label="Graph" />);
    flush();
    const canvas = screen.getByRole("img", { name: "Graph" });
    const at = screenOf(scene, "n1");
    fireEvent.pointerMove(canvas, at);
    expect(canvas.style.cursor).toBe("pointer");
    fireEvent.pointerDown(canvas, at);
    fireEvent.pointerUp(canvas, at);
    expect(onSelect).toHaveBeenLastCalledWith("n1");
    fireEvent.pointerDown(canvas, { clientX: 2, clientY: 2 });
    fireEvent.pointerUp(canvas, { clientX: 2, clientY: 2 });
    expect(onSelect).toHaveBeenLastCalledWith(null);
    fireEvent.pointerLeave(canvas);
    expect(canvas.style.cursor).toBe("grab");
  });

  it("pans on a drag without selecting, and zooms with the wheel and the buttons", () => {
    const scene = sceneOf(3);
    const onSelect = vi.fn();
    render(<CardCanvas scene={scene} selectedId={null} onSelect={onSelect} label="Graph" />);
    flush();
    const canvas = screen.getByRole("img", { name: "Graph" });
    const start = screenOf(scene, "n1");
    fireEvent.pointerDown(canvas, start);
    fireEvent.pointerMove(canvas, { clientX: start.clientX + 60, clientY: start.clientY + 10 });
    fireEvent.pointerUp(canvas, { clientX: start.clientX + 60, clientY: start.clientY + 10 });
    expect(onSelect).not.toHaveBeenCalled();
    flush();

    const level = () => screen.getByLabelText(/%/).textContent;
    const before = level();
    act(() => {
      canvas.dispatchEvent(new WheelEvent("wheel", { deltaY: -200, clientX: 100, clientY: 100, bubbles: true, cancelable: true }));
    });
    flush();
    expect(level()).not.toBe(before);

    const afterWheel = level();
    fireEvent.click(screen.getByRole("button", { name: t("cardGraph.zoomOut") }));
    now = 1000;
    flush(2);
    expect(level()).not.toBe(afterWheel);
    fireEvent.click(screen.getByRole("button", { name: t("cardGraph.zoomIn") }));
    fireEvent.click(screen.getByRole("button", { name: t("cardGraph.fit") }));
    now = 2000;
    flush(2);
    expect(level()).toBe(before);
  });

  it("shows a minimap for a large scene and moves the view from it", () => {
    const scene = sceneOf(16);
    const { container } = render(
      <CardCanvas scene={scene} selectedId="n3" onSelect={() => {}} label="Graph" />,
    );
    flush(2);
    const mini = container.querySelector("canvas[aria-hidden]");
    expect(mini).not.toBeNull();
    if (!mini) return;
    fireEvent.pointerDown(mini, { clientX: 20, clientY: 20 });
    fireEvent.pointerMove(mini, { clientX: 60, clientY: 40 });
    fireEvent.pointerUp(mini);
    flush();
  });

  it("stays static without interaction: no toolbar, no minimap", () => {
    const scene = sceneOf(16);
    const onSelect = vi.fn();
    const { container } = render(
      <CardCanvas scene={scene} selectedId="n0" onSelect={onSelect} label="Mini" interactive={false} focusSelection={false} />,
    );
    flush();
    expect(screen.queryByRole("button", { name: t("cardGraph.fit") })).toBeNull();
    expect(container.querySelector("canvas[aria-hidden]")).toBeNull();
  });
});
