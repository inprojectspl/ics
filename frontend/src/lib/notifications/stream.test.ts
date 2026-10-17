import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeEventSource, installStreamFakes, removeStreamFakes } from "../../test-stream-fakes";
import { mkItem } from "../../test-notifications";
import { STREAM_RETRY_MS, openNotificationStream, type StreamHandle } from "./stream";

const flush = () => new Promise((r) => setTimeout(r, 0));
const stops: (() => void)[] = [];
const handles: StreamHandle[] = [];

function tab() {
  const events = vi.fn();
  const stream = openNotificationStream(events);
  stops.push(stream.close);
  handles.push(stream);
  return events;
}

afterEach(() => {
  for (const stop of stops.splice(0)) stop();
  handles.splice(0);
  vi.useRealTimers();
  removeStreamFakes();
});

describe("with Web Locks", () => {
  beforeEach(() => installStreamFakes());

  it("opens one stream for all tabs and relays its events", async () => {
    const leader = tab();
    const follower = tab();
    await flush();
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.instances[0]?.url).toBe("/api/notifications/stream");
    expect(handles.map((h) => h.live())).toEqual([true, true]);

    const item = mkItem();
    FakeEventSource.instances[0]?.emit("notification", { item, unread: 2 });
    FakeEventSource.instances[0]?.emit("sync", { unread: 1, read: [item.id] });
    const expected = [
      { type: "notification", data: { item, unread: 2 } },
      { type: "sync", data: { unread: 1, read: [item.id] } },
    ];
    expect(leader.mock.calls.map((c) => c[0])).toEqual(expected);
    expect(follower.mock.calls.map((c) => c[0])).toEqual(expected);
  });

  it("hands the stream to a waiting tab, which refetches what it may have missed", async () => {
    tab();
    const follower = tab();
    await flush();
    stops[0]?.();
    await flush();
    expect(FakeEventSource.open).toHaveLength(1);
    expect(FakeEventSource.instances).toHaveLength(2);
    expect(follower).toHaveBeenCalledWith({ type: "reset" });
  });

  it("ignores malformed events and stops everything on cleanup", async () => {
    const events = tab();
    await flush();
    const es = FakeEventSource.instances[0];
    es?.emit("notification", "not json");
    es?.emit("notification", { unread: 1 });
    es?.emit("sync", { read: [] });
    es?.emit("reset", "");
    expect(events.mock.calls).toEqual([[{ type: "reset" }]]);
    stops[0]?.();
    expect(es?.readyState).toBe(2);
  });
});

describe("without Web Locks", () => {
  beforeEach(() => installStreamFakes({ locks: false }));

  it("keeps a stream per tab and relays nothing", async () => {
    const a = tab();
    const b = tab();
    await flush();
    expect(FakeEventSource.instances).toHaveLength(2);
    FakeEventSource.instances[0]?.emit("reset", "");
    expect(a).toHaveBeenCalledTimes(1);
    expect(b).not.toHaveBeenCalled();
  });

  it("reopens a closed stream after a pause, a network blip is left to the browser", () => {
    vi.useFakeTimers();
    const events = tab();
    const first = FakeEventSource.instances[0];
    first?.fail(false);
    vi.advanceTimersByTime(STREAM_RETRY_MS);
    expect(FakeEventSource.instances).toHaveLength(1);

    first?.fail(true);
    expect(handles[0]?.live()).toBe(false);
    vi.advanceTimersByTime(STREAM_RETRY_MS);
    expect(FakeEventSource.instances).toHaveLength(2);
    expect(events).toHaveBeenCalledWith({ type: "reset" });
  });

  it("reports whether events are arriving", () => {
    const onLive = vi.fn();
    const stream = openNotificationStream(vi.fn(), onLive);
    stops.push(stream.close);
    expect(onLive.mock.calls).toEqual([[true]]);
    FakeEventSource.instances[0]?.fail(false);
    expect(onLive).toHaveBeenLastCalledWith(false);
    FakeEventSource.instances[0]?.reopen();
    expect(onLive).toHaveBeenLastCalledWith(true);
    stream.close();
    expect(onLive).toHaveBeenLastCalledWith(false);
  });

  it("does not retry after cleanup", () => {
    vi.useFakeTimers();
    tab();
    FakeEventSource.instances[0]?.fail(true);
    stops[0]?.();
    vi.advanceTimersByTime(STREAM_RETRY_MS);
    expect(FakeEventSource.instances).toHaveLength(1);
  });
});

describe("without EventSource", () => {
  it("does nothing", () => {
    vi.stubGlobal("EventSource", undefined);
    vi.stubGlobal("BroadcastChannel", undefined);
    expect(() => tab()).not.toThrow();
  });
});
