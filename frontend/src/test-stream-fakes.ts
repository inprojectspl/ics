// Browser APIs of the live stream (EventSource, Web Locks, BroadcastChannel)
// as in-memory fakes, shared by the stream and bell tests.
import { vi } from "vitest";

export class FakeEventSource {
  static instances: FakeEventSource[] = [];
  readyState = 1;
  onerror: (() => void) | null = null;
  onopen: (() => void) | null = null;
  private listeners = new Map<string, ((e: MessageEvent) => void)[]>();

  constructor(
    readonly url: string,
    readonly init?: EventSourceInit,
  ) {
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, fn: (e: MessageEvent) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), fn]);
  }

  close() {
    this.readyState = 2;
  }

  emit(type: string, data: unknown) {
    const raw = typeof data === "string" ? data : JSON.stringify(data);
    for (const fn of this.listeners.get(type) ?? []) fn(new MessageEvent(type, { data: raw }));
  }

  reopen() {
    this.readyState = 1;
    this.onopen?.();
  }

  fail(closed: boolean) {
    this.readyState = closed ? 2 : 0;
    this.onerror?.();
  }

  static get open(): FakeEventSource[] {
    return FakeEventSource.instances.filter((s) => s.readyState !== 2);
  }
}

class FakeBroadcastChannel {
  static channels: FakeBroadcastChannel[] = [];
  onmessage: ((e: MessageEvent) => void) | null = null;
  closed = false;

  constructor(readonly name: string) {
    FakeBroadcastChannel.channels.push(this);
  }

  postMessage(data: unknown) {
    for (const other of FakeBroadcastChannel.channels) {
      if (other !== this && !other.closed && other.name === this.name) {
        other.onmessage?.(new MessageEvent("message", { data }));
      }
    }
  }

  close() {
    this.closed = true;
  }
}

type Callback = (lock: { name: string } | null) => unknown;

/** One exclusive lock with a FIFO queue, enough for leader election. */
class FakeLocks {
  private held = false;
  private queue: (() => void)[] = [];

  request(name: string, options: { ifAvailable?: boolean; signal?: AbortSignal }, cb: Callback): Promise<unknown> {
    if (options.ifAvailable && this.held) return Promise.resolve(cb(null));
    return new Promise((resolve, reject) => {
      const run = () => {
        this.held = true;
        void Promise.resolve(cb({ name })).then((value) => {
          this.held = false;
          this.queue.shift()?.();
          resolve(value);
        });
      };
      if (!this.held) {
        run();
        return;
      }
      this.queue.push(run);
      options.signal?.addEventListener("abort", () => {
        this.queue = this.queue.filter((q) => q !== run);
        reject(new DOMException("aborted", "AbortError"));
      });
    });
  }
}

export function installStreamFakes({ locks = true } = {}) {
  FakeEventSource.instances = [];
  FakeBroadcastChannel.channels = [];
  vi.stubGlobal("EventSource", FakeEventSource);
  vi.stubGlobal("BroadcastChannel", FakeBroadcastChannel);
  Object.defineProperty(navigator, "locks", {
    value: locks ? new FakeLocks() : undefined,
    configurable: true,
  });
}

export function removeStreamFakes() {
  vi.unstubAllGlobals();
  Object.defineProperty(navigator, "locks", { value: undefined, configurable: true });
}
