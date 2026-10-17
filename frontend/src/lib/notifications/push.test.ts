import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const savePushSubscription = vi.fn();
const unsubscribePush = vi.fn();
vi.mock("../../api/notifications", () => ({
  savePushSubscription: (...a: unknown[]) => savePushSubscription(...a),
  unsubscribePush: (...a: unknown[]) => unsubscribePush(...a),
}));

import {
  base64UrlToBytes,
  deviceLabel,
  disablePushHere,
  enablePush,
  hasPushHere,
  isBrave,
  pushSupport,
  thisDeviceId,
} from "./push";

const CHROME_MAC =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36";
const IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile Safari/604.1";

function stubUa(ua: string) {
  vi.spyOn(navigator, "userAgent", "get").mockReturnValue(ua);
}

const subscription = {
  endpoint: "https://fcm.googleapis.com/fcm/send/x",
  toJSON: () => ({ keys: { p256dh: "pk", auth: "au" } }),
  unsubscribe: vi.fn().mockResolvedValue(true),
};

function stubPush({ existing = null as typeof subscription | null, permission = "default" } = {}) {
  const pushManager = {
    getSubscription: vi.fn().mockResolvedValue(existing),
    subscribe: vi.fn().mockResolvedValue(subscription),
  };
  const reg = { pushManager };
  const serviceWorker = {
    register: vi.fn().mockResolvedValue(reg),
    ready: Promise.resolve(reg),
    getRegistration: vi.fn().mockResolvedValue(reg),
  };
  Object.defineProperty(navigator, "serviceWorker", { value: serviceWorker, configurable: true });
  vi.stubGlobal("PushManager", function PushManager() {});
  const requestPermission = vi.fn().mockResolvedValue("granted");
  vi.stubGlobal("Notification", { permission, requestPermission });
  return { pushManager, serviceWorker, requestPermission };
}

beforeEach(() => {
  savePushSubscription.mockReset().mockResolvedValue({ id: "d1" });
  unsubscribePush.mockReset().mockResolvedValue(undefined);
  localStorage.clear();
  stubUa(CHROME_MAC);
});

afterEach(() => {
  vi.unstubAllGlobals();
  Object.defineProperty(navigator, "serviceWorker", { value: undefined, configurable: true });
});

describe("helpers", () => {
  it("decodes a base64url VAPID key", () => {
    expect(Array.from(base64UrlToBytes("AQID_-8"))).toEqual([1, 2, 3, 255, 239]);
  });

  it("labels the device by browser and system", () => {
    expect(deviceLabel(CHROME_MAC)).toBe("Chrome · macOS");
    expect(deviceLabel(IPHONE)).toBe("Safari · iOS");
    expect(deviceLabel("curl/8")).toBe("Browser");
  });

  it("detects Brave", () => {
    expect(isBrave()).toBe(false);
  });
});

describe("pushSupport", () => {
  it("needs a service worker, PushManager and Notification", () => {
    expect(pushSupport()).toBe("unsupported");
    stubPush();
    expect(pushSupport()).toBe("supported");
    stubPush({ permission: "denied" });
    expect(pushSupport()).toBe("denied");
  });

  it("asks iOS users to add the app to the home screen first", () => {
    stubUa(IPHONE);
    stubPush();
    expect(pushSupport()).toBe("ios-install");
  });
});

describe("enablePush", () => {
  it("asks for permission, subscribes with the server key and stores the device", async () => {
    const { pushManager, serviceWorker, requestPermission } = stubPush();
    await expect(enablePush("AQID")).resolves.toBe("enabled");
    expect(requestPermission).toHaveBeenCalled();
    expect(serviceWorker.register).toHaveBeenCalledWith("/sw.js", { scope: "/" });
    expect(pushManager.subscribe).toHaveBeenCalledWith(expect.objectContaining({ userVisibleOnly: true }));
    expect(savePushSubscription).toHaveBeenCalledWith({
      endpoint: subscription.endpoint,
      keys: { p256dh: "pk", auth: "au" },
      label: "Chrome · macOS",
    });
    expect(thisDeviceId()).toBe("d1");
  });

  it("reuses an existing subscription", async () => {
    const { pushManager } = stubPush({ existing: subscription });
    await enablePush("AQID");
    expect(pushManager.subscribe).not.toHaveBeenCalled();
  });

  it("stops when the permission is refused", async () => {
    const { requestPermission, serviceWorker } = stubPush();
    requestPermission.mockResolvedValue("denied");
    await expect(enablePush("AQID")).resolves.toBe("denied");
    expect(serviceWorker.register).not.toHaveBeenCalled();
  });
});

describe("disablePushHere", () => {
  it("tells the server first, then drops the subscription", async () => {
    stubPush({ existing: subscription });
    localStorage.setItem("ics-push-device", "d1");
    await expect(hasPushHere()).resolves.toBe(true);
    await disablePushHere();
    expect(unsubscribePush).toHaveBeenCalledWith(subscription.endpoint);
    expect(subscription.unsubscribe).toHaveBeenCalled();
    expect(thisDeviceId()).toBeNull();
  });

  it("knows when this browser has no subscription", async () => {
    await expect(hasPushHere()).resolves.toBe(false);
    stubPush();
    await expect(hasPushHere()).resolves.toBe(false);
  });
});
