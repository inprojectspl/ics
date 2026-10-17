import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { FakeEventSource, installStreamFakes, removeStreamFakes } from "../../test-stream-fakes";
import { mkInbox, mkItem } from "../../test-notifications";
import { qk } from "../queries";
import { inboxItems, type Inbox } from "./cache";
import { SW_PUSH_MESSAGE, useNotificationStream, useUnreadIndicators } from "./useNotificationStream";

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, wrapper };
}

beforeEach(() => installStreamFakes({ locks: false }));
afterEach(() => removeStreamFakes());

describe("useNotificationStream", () => {
  it("writes live events into the cached summary and lists", () => {
    const { client, wrapper } = setup();
    const old = mkItem();
    client.setQueryData(qk.notificationList("all"), mkInbox([old]));
    client.setQueryData(qk.notificationList("unread"), mkInbox([old]));
    const onNew = vi.fn();
    renderHook(() => useNotificationStream(onNew), { wrapper });
    const es = FakeEventSource.instances[0];

    const fresh = mkItem();
    act(() => es?.emit("notification", { item: fresh, unread: 2 }));
    expect(client.getQueryData(qk.notificationSummary())).toEqual({ unread: 2 });
    expect(inboxItems(client.getQueryData<Inbox>(qk.notificationList("all")))).toHaveLength(2);
    expect(onNew).toHaveBeenCalledWith(fresh);

    act(() => es?.emit("sync", { unread: 0, all_read: true }));
    expect(client.getQueryData(qk.notificationSummary())).toEqual({ unread: 0 });
    expect(inboxItems(client.getQueryData<Inbox>(qk.notificationList("unread"))).every((x) => x.read)).toBe(true);
  });

  it("refetches everything on reset and closes the stream on unmount", () => {
    const { client, wrapper } = setup();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { unmount } = renderHook(() => useNotificationStream(), { wrapper });
    act(() => FakeEventSource.instances[0]?.emit("reset", ""));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.notifications() });
    unmount();
    expect(FakeEventSource.instances[0]?.readyState).toBe(2);
  });

  it("refreshes the badge on a push from the service worker only without a live stream", () => {
    const { client, wrapper } = setup();
    const target = new EventTarget();
    Object.defineProperty(navigator, "serviceWorker", { value: target, configurable: true });
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { unmount } = renderHook(() => useNotificationStream(), { wrapper });
    target.dispatchEvent(new MessageEvent("message", { data: { type: "other" } }));
    expect(invalidate).not.toHaveBeenCalled();
    // The stream is open: the push is already in the cache.
    target.dispatchEvent(new MessageEvent("message", { data: { type: SW_PUSH_MESSAGE } }));
    expect(invalidate).not.toHaveBeenCalled();
    FakeEventSource.instances[0]?.fail(true);
    target.dispatchEvent(new MessageEvent("message", { data: { type: SW_PUSH_MESSAGE } }));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.notificationSummary() });
    unmount();
    Object.defineProperty(navigator, "serviceWorker", { value: undefined, configurable: true });
  });
});

describe("useUnreadIndicators", () => {
  it("prefixes the title while mounted", () => {
    document.title = "ICS";
    const { rerender, unmount } = renderHook(({ n }) => useUnreadIndicators(n), {
      initialProps: { n: undefined as number | undefined },
    });
    expect(document.title).toBe("ICS");
    rerender({ n: 5 });
    expect(document.title).toBe("(5) ICS");
    unmount();
    expect(document.title).toBe("ICS");
  });
});
