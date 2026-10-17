import { afterEach, describe, expect, it, vi } from "vitest";
import { observeOnce } from "./lazyObserve";

/** Controllable fake IntersectionObserver, since jsdom has none. */
class FakeIO {
  static instances: FakeIO[] = [];
  readonly root = null;
  readonly rootMargin: string;
  readonly thresholds: ReadonlyArray<number> = [];
  observed: Element[] = [];
  disconnected = false;
  private cb: IntersectionObserverCallback;

  constructor(cb: IntersectionObserverCallback, opts?: IntersectionObserverInit) {
    this.cb = cb;
    this.rootMargin = String(opts?.rootMargin ?? "");
    FakeIO.instances.push(this);
  }
  observe(el: Element): void {
    this.observed.push(el);
  }
  unobserve(): void {}
  disconnect(): void {
    this.disconnected = true;
  }
  takeRecords(): IntersectionObserverEntry[] {
    return [];
  }
  /** Simulate the element entering (or leaving) the viewport. */
  fire(target: Element, isIntersecting: boolean): void {
    this.cb(
      [{ target, isIntersecting } as IntersectionObserverEntry],
      this as unknown as IntersectionObserver,
    );
  }
}

afterEach(() => {
  FakeIO.instances = [];
  vi.unstubAllGlobals();
});

describe("observeOnce with IntersectionObserver", () => {
  it("calls cb only on entering the viewport and disconnects the observer", () => {
    vi.stubGlobal("IntersectionObserver", FakeIO);
    const el = document.createElement("div");
    const cb = vi.fn();

    observeOnce(el, cb);
    const io = FakeIO.instances[0];
    expect(io?.observed).toContain(el);
    expect(cb).not.toHaveBeenCalled(); // still outside the viewport

    io?.fire(el, false);
    expect(cb).not.toHaveBeenCalled(); // still outside the viewport

    io?.fire(el, true);
    expect(cb).toHaveBeenCalledTimes(1);
    expect(io?.disconnected).toBe(true); // one-shot
  });

  it("uses a 200px rootMargin to render before entering the viewport", () => {
    vi.stubGlobal("IntersectionObserver", FakeIO);
    observeOnce(document.createElement("div"), vi.fn());
    expect(FakeIO.instances[0]?.rootMargin).toBe("200px 0px");
  });

  it("is idempotent: a second observeOnce on the same element is a no-op", () => {
    vi.stubGlobal("IntersectionObserver", FakeIO);
    const el = document.createElement("div");
    observeOnce(el, vi.fn());
    observeOnce(el, vi.fn());
    expect(FakeIO.instances).toHaveLength(1); // no second observer
  });
});

describe("observeOnce without IntersectionObserver", () => {
  it("calls cb synchronously when IntersectionObserver is unavailable", () => {
    // jsdom has no IntersectionObserver by default, so nothing is stubbed.
    expect("IntersectionObserver" in window).toBe(false);
    const cb = vi.fn();
    observeOnce(document.createElement("div"), cb);
    expect(cb).toHaveBeenCalledTimes(1);
  });
});
