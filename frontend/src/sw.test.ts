import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

type Handler = (e: unknown) => void;
const handlers = new Map<string, Handler>();
const clients = { matchAll: vi.fn(), openWindow: vi.fn(), claim: vi.fn() };
const registration = { showNotification: vi.fn() };
const scope = {
  location: new URL("https://ics.example/"),
  clients,
  registration,
  skipWaiting: vi.fn(),
  addEventListener: (type: string, fn: Handler) => handlers.set(type, fn),
};

beforeAll(async () => {
  vi.stubGlobal("self", scope);
  // A script, not a module: the cast keeps tsc from asking for exports.
  await import("./sw" as string);
  vi.unstubAllGlobals();
});

function fire(type: string, event: object): Promise<unknown> {
  let pending: Promise<unknown> = Promise.resolve();
  handlers.get(type)?.({ ...event, waitUntil: (p: Promise<unknown>) => (pending = p) });
  return pending;
}

const payload = { title: "ICS", body: "API spec: 3 new versions", url: "/v/abc", tag: "asset.updated:a1" };

function client(over: object = {}) {
  return {
    url: "https://ics.example/",
    focused: false,
    postMessage: vi.fn(),
    focus: vi.fn(),
    navigate: vi.fn().mockResolvedValue(null),
    ...over,
  };
}

beforeEach(() => {
  for (const fn of [clients.matchAll, clients.openWindow, registration.showNotification]) fn.mockReset();
  clients.matchAll.mockResolvedValue([]);
});

describe("service worker", () => {
  it("shows an OS notification that replaces the previous one for the same asset", async () => {
    await fire("push", { data: { json: () => payload } });
    expect(registration.showNotification).toHaveBeenCalledWith("ICS", {
      body: payload.body,
      tag: payload.tag,
      renotify: true,
      icon: "/icons/icon-192.png",
      data: { url: "/v/abc" },
    });
  });

  it("hands the event to a focused tab instead", async () => {
    const focused = client({ focused: true });
    clients.matchAll.mockResolvedValue([client(), focused]);
    await fire("push", { data: { json: () => payload } });
    expect(focused.postMessage).toHaveBeenCalledWith({ type: "ics-push", payload });
    expect(registration.showNotification).not.toHaveBeenCalled();
  });

  it("ignores a push without a usable payload", async () => {
    await fire("push", { data: null });
    await fire("push", { data: { json: () => { throw new Error("not json"); } } });
    expect(registration.showNotification).not.toHaveBeenCalled();
  });

  it("focuses an open tab and navigates it on click", async () => {
    const tab = client();
    tab.focus.mockResolvedValue(tab);
    clients.matchAll.mockResolvedValue([tab]);
    const close = vi.fn();
    await fire("notificationclick", { notification: { close, data: { url: "/v/abc" } } });
    expect(close).toHaveBeenCalled();
    expect(tab.navigate).toHaveBeenCalledWith("https://ics.example/v/abc");
    expect(clients.openWindow).not.toHaveBeenCalled();
  });

  it("opens a window when no tab can be navigated, and never leaves the origin", async () => {
    const tab = client({ navigate: vi.fn().mockRejectedValue(new TypeError("not controlled")) });
    tab.focus.mockResolvedValue(tab);
    clients.matchAll.mockResolvedValue([tab]);
    await fire("notificationclick", { notification: { close: vi.fn(), data: { url: "/notifications" } } });
    expect(clients.openWindow).toHaveBeenCalledWith("https://ics.example/notifications");

    clients.matchAll.mockResolvedValue([]);
    await fire("notificationclick", { notification: { close: vi.fn(), data: { url: "https://evil.example/x" } } });
    expect(clients.openWindow).toHaveBeenLastCalledWith("https://ics.example");
  });
});
