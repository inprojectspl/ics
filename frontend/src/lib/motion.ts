import { useEffect, useLayoutEffect, useState, type RefObject } from "react";
import { waapi } from "animejs/waapi";

/**
 * Motion durations (DESIGN.md 13.1) for the Anime.js transitions. Only
 * `transform` and `opacity` animate; interactive state (focus,
 * `aria-expanded`, routing) changes at once, never waiting on an animation.
 */
const MOTION = {
  /** Micro feedback: a confirmation tick, a badge bump. */
  micro: 140,
  /** Menus, popovers, disclosures. */
  menu: 170,
  /** Drawers and sheets. */
  drawer: 230,
  /** Same curve as `--ease-standard` in theme.css. */
  ease: "cubic-bezier(0.2, 0.8, 0.2, 1)",
} as const;

export type MotionPreset =
  | "menu"
  | "menu-up"
  | "reveal"
  | "fade"
  | "drawer-left"
  | "drawer-right"
  | "sheet"
  | "dialog"
  | "bump";

interface Keyframes {
  opacity?: [number, number];
  transform?: [string, string];
  duration: number;
}

// Offsets stay within 8-16 px: the element slides into place, it does not
// fly in from a distance.
const PRESETS: Record<MotionPreset, Keyframes> = {
  menu: { opacity: [0, 1], transform: ["translateY(-4px) scale(0.985)", "none"], duration: MOTION.menu },
  "menu-up": { opacity: [0, 1], transform: ["translateY(4px) scale(0.985)", "none"], duration: MOTION.menu },
  reveal: { opacity: [0, 1], transform: ["translateY(-4px)", "none"], duration: MOTION.menu },
  fade: { opacity: [0, 1], duration: MOTION.menu },
  "drawer-left": { opacity: [0.4, 1], transform: ["translateX(-16px)", "none"], duration: MOTION.drawer },
  "drawer-right": { opacity: [0.4, 1], transform: ["translateX(16px)", "none"], duration: MOTION.drawer },
  sheet: { opacity: [0.6, 1], transform: ["translateY(16px)", "none"], duration: MOTION.drawer },
  dialog: { opacity: [0, 1], transform: ["translateY(8px) scale(0.99)", "none"], duration: MOTION.drawer },
  bump: { transform: ["scale(1.18)", "none"], duration: MOTION.micro },
};

const REDUCED_QUERY = "(prefers-reduced-motion: reduce)";

/** Checked on every play, not cached: the setting can change while the tab is open. */
export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && Boolean(window.matchMedia?.(REDUCED_QUERY).matches);
}

type Running = ReturnType<typeof waapi.animate>;
// One animation per element: a new one reverts the previous, so quick
// open-close-open never stacks two timelines on the same transform.
const running = new WeakMap<Element, Running>();

function canAnimate(el: Element | null | undefined): el is HTMLElement {
  return (
    el instanceof HTMLElement && typeof el.animate === "function" && !prefersReducedMotion()
  );
}

function stop(el: Element) {
  running.get(el)?.revert();
  running.delete(el);
}

function play(el: HTMLElement, preset: MotionPreset, reverse: boolean): Running {
  stop(el);
  const { duration, opacity, transform } = PRESETS[preset];
  const params: Record<string, [number, number] | [string, string]> = {};
  if (opacity) params.opacity = reverse ? [opacity[1], opacity[0]] : opacity;
  if (transform) params.transform = reverse ? [transform[1], transform[0]] : transform;
  const anim = waapi.animate(el, {
    ...params,
    duration: reverse ? Math.round(duration * 0.75) : duration,
    ease: MOTION.ease,
  });
  running.set(el, anim);
  return anim;
}

/** Plays the entrance of `el`; a no-op under reduced motion or without WAAPI. */
export function playEnter(el: Element | null | undefined, preset: MotionPreset): void {
  if (!canAnimate(el)) return;
  const anim = play(el, preset, false);
  // Hand the element back its own inline style once done: a leftover
  // inline transform would make it the containing block of fixed children.
  void anim.then(() => {
    if (running.get(el) === anim) stop(el);
  });
}

/** Plays the exit of `el` and resolves when it is safe to unmount. Resolves
 * at once when there is nothing to animate, never blocks the caller. */
export function playExit(el: Element | null | undefined, preset: MotionPreset): Promise<void> {
  if (!canAnimate(el)) return Promise.resolve();
  const anim = play(el, preset, true);
  return new Promise((resolve) => {
    void anim.then(() => resolve());
    // A reverted (interrupted) exit never completes; do not hang the caller.
    window.setTimeout(resolve, PRESETS[preset].duration + 80);
  });
}

/** Cancels whatever runs on `el` and restores its style. */
export function cancelMotion(el: Element | null | undefined): void {
  if (el) stop(el);
}

/** Entrance animation for an element mounted while `active` is true. */
export function useEnterMotion(
  ref: RefObject<Element | null>,
  preset: MotionPreset,
  active = true,
): void {
  useLayoutEffect(() => {
    if (!active) return;
    const el = ref.current;
    playEnter(el, preset);
    return () => cancelMotion(el);
  }, [ref, preset, active]);
}

/**
 * Keeps an overlay mounted while its exit animation runs. `open` is the
 * source of truth: the returned flag turns true with it at once, and turns
 * false only after the exit (or immediately under reduced motion). Focus
 * handling and Escape work on `open`, never on the animation.
 */
export function usePresence(
  open: boolean,
  ref: RefObject<Element | null>,
  preset: MotionPreset,
): boolean {
  const [shown, setShown] = useState(open);
  if (open && !shown) setShown(true);

  useLayoutEffect(() => {
    if (!open || !shown) return;
    const el = ref.current;
    playEnter(el, preset);
  }, [open, shown, ref, preset]);

  useEffect(() => {
    if (open || !shown) return;
    let alive = true;
    void playExit(ref.current, preset).then(() => {
      if (alive) setShown(false);
    });
    return () => {
      alive = false;
    };
  }, [open, shown, ref, preset]);

  return shown;
}
