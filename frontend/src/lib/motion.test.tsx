import { useRef } from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { mockMedia } from "../test-media";
import { cancelMotion, playEnter, playExit, prefersReducedMotion, usePresence } from "./motion";

function Presence({ open }: { open: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const shown = usePresence(open, ref, "drawer-left");
  return shown ? <div ref={ref}>panel</div> : null;
}

describe("motion", () => {
  it("reads the reduced-motion preference on every call", () => {
    mockMedia({ reducedMotion: true });
    expect(prefersReducedMotion()).toBe(true);
    mockMedia({ reducedMotion: false });
    expect(prefersReducedMotion()).toBe(false);
  });

  it("never animates under reduced motion", async () => {
    mockMedia({ reducedMotion: true });
    const el = document.createElement("div");
    const animate = vi.fn();
    (el as unknown as { animate: typeof animate }).animate = animate;
    playEnter(el, "menu");
    await playExit(el, "menu");
    expect(animate).not.toHaveBeenCalled();
  });

  it("resolves at once without Web Animations and tolerates missing elements", async () => {
    await expect(playExit(document.createElement("div"), "sheet")).resolves.toBeUndefined();
    await expect(playExit(null, "sheet")).resolves.toBeUndefined();
    expect(() => {
      playEnter(undefined, "fade");
      cancelMotion(null);
    }).not.toThrow();
  });

  it("usePresence mounts at once and unmounts after the exit", async () => {
    const { rerender } = render(<Presence open={false} />);
    expect(screen.queryByText("panel")).not.toBeInTheDocument();
    rerender(<Presence open />);
    expect(screen.getByText("panel")).toBeInTheDocument();
    rerender(<Presence open={false} />);
    // The exit keeps it mounted for its animation, then it goes.
    await waitFor(() => expect(screen.queryByText("panel")).not.toBeInTheDocument());
  });

  it("reopening during the exit keeps the element", async () => {
    const { rerender } = render(<Presence open />);
    rerender(<Presence open={false} />);
    rerender(<Presence open />);
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.getByText("panel")).toBeInTheDocument();
  });

  it("with Web Animations it plays transform and opacity, and hands the style back", async () => {
    mockMedia({ reducedMotion: false });
    const el = document.createElement("div");
    document.body.appendChild(el);
    const made: Array<Record<string, unknown>> = [];
    (el as unknown as { animate: unknown }).animate = vi.fn((keyframes: Record<string, unknown>) => {
      const anim: Record<string, unknown> = {
        keyframes,
        currentTime: 0,
        playbackRate: 1,
        play: vi.fn(),
        pause: vi.fn(),
        cancel: vi.fn(),
        commitStyles: vi.fn(),
        finished: Promise.resolve(),
        onfinish: null,
        oncancel: null,
      };
      made.push(anim);
      queueMicrotask(() => (anim.onfinish as (() => void) | null)?.());
      return anim;
    });
    playEnter(el, "menu");
    await playExit(el, "dialog");
    cancelMotion(el);
    expect((el as unknown as { animate: ReturnType<typeof vi.fn> }).animate).toHaveBeenCalled();
    const props = made.flatMap((a) => Object.keys(a.keyframes as object));
    expect(props.every((p) => ["opacity", "transform"].includes(p))).toBe(true);
    el.remove();
  });
});
