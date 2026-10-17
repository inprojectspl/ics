/** Request contract of the notification endpoints (docs/notifications-api.md). */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as n from "./notifications";

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset().mockImplementation(async () => new Response("{}", { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function lastCall() {
  const [url, init = {}] = fetchMock.mock.calls.at(-1) as [string, RequestInit?];
  const raw = init.body;
  return {
    url,
    method: init.method ?? "GET",
    body: typeof raw === "string" ? JSON.parse(raw) : raw,
    keepalive: init.keepalive,
  };
}

type Case = [name: string, call: () => Promise<unknown>, method: string, url: string, body?: unknown];

const sub = { endpoint: "https://fcm.googleapis.com/x", keys: { p256dh: "p", auth: "a" }, label: "Chrome" };

const cases: Case[] = [
  ["list", () => n.listNotifications(), "GET", "/api/notifications?limit=30"],
  [
    "list page unread",
    () => n.listNotifications({ before: "17-0", filter: "unread", limit: 10 }),
    "GET",
    "/api/notifications?before=17-0&limit=10&unread=true",
  ],
  ["summary", () => n.notificationSummary(), "GET", "/api/notifications/summary"],
  ["markRead", () => n.markRead(["a", "b"]), "POST", "/api/notifications/read", { ids: ["a", "b"] }],
  ["markAllRead", () => n.markAllRead(), "POST", "/api/notifications/read", { all: true }],
  ["markUnread", () => n.markUnread(["a"]), "POST", "/api/notifications/unread", { ids: ["a"] }],
  ["delete", () => n.deleteNotification("17-0"), "DELETE", "/api/notifications/17-0"],
  ["clear", () => n.clearNotifications(), "DELETE", "/api/notifications"],
  ["preferences", () => n.getPreferences(), "GET", "/api/notifications/preferences"],
  [
    "update preferences",
    () => n.updatePreferences({ chat_webhook_url: null, email_mode: "daily" }),
    "PUT",
    "/api/notifications/preferences",
    { chat_webhook_url: null, email_mode: "daily" },
  ],
  ["chat test", () => n.sendChatTest(), "POST", "/api/notifications/chat/test", {}],
  ["push devices", () => n.listPushDevices(), "GET", "/api/notifications/push/subscriptions"],
  ["save push", () => n.savePushSubscription(sub), "PUT", "/api/notifications/push/subscriptions", sub],
  ["unsubscribe push", () => n.unsubscribePush("e"), "POST", "/api/notifications/push/unsubscribe", { endpoint: "e" }],
  ["delete push", () => n.deletePushDevice("d1"), "DELETE", "/api/notifications/push/subscriptions/d1"],
  ["email opt-out", () => n.unsubscribeEmail("tok"), "POST", "/api/notifications/unsubscribe", { token: "tok" }],
  ["asset watch", () => n.getAssetWatch("a1"), "GET", "/api/assets/a1/watch"],
  ["watch asset", () => n.setAssetWatch("a1", "mute"), "PUT", "/api/assets/a1/watch", { level: "mute" }],
  ["unwatch asset", () => n.clearAssetWatch("a1"), "DELETE", "/api/assets/a1/watch"],
  ["project watch", () => n.getProjectWatch("crm"), "GET", "/api/projects/crm/watch"],
  ["watch project", () => n.setProjectWatch("crm", "all"), "PUT", "/api/projects/crm/watch", { level: "all" }],
  ["unwatch project", () => n.clearProjectWatch("crm"), "DELETE", "/api/projects/crm/watch"],
  ["watches page 2", () => n.listWatches(2), "GET", "/api/watches?page=2&page_size=25"],
];

describe("notification endpoints", () => {
  it.each(cases)("%s", async (_name, call, method, url, body) => {
    await call();
    const sent = lastCall();
    expect(sent.method).toBe(method);
    expect(sent.url).toBe(url);
    if (body !== undefined) expect(sent.body).toEqual(body);
  });

  it("keeps the mark-read request alive when the row click leaves the page", async () => {
    await n.markRead(["a"]);
    expect(lastCall().keepalive).toBe(true);
  });
});
