// Web Push on this device (ADR-0023, section 7): permission only after a
// click, then the service worker at `/sw.js` and a push subscription the
// backend stores as one device.
import { savePushSubscription, unsubscribePush } from "../../api/notifications";

const SW_URL = "/sw.js";
const DEVICE_KEY = "ics-push-device";

export type PushSupport = "supported" | "unsupported" | "ios-install" | "denied";

function isIos(ua: string): boolean {
  return /iPad|iPhone|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
}

function isStandalone(): boolean {
  return Boolean(window.matchMedia?.("(display-mode: standalone)")?.matches);
}

/** What the browser allows here. iOS offers push only to a web app added to
 * the home screen (Safari 16.4+). */
export function pushSupport(): PushSupport {
  const ua = navigator.userAgent;
  if (isIos(ua) && !isStandalone()) return "ios-install";
  if (!("serviceWorker" in navigator) || typeof PushManager === "undefined") return "unsupported";
  if (typeof Notification === "undefined") return "unsupported";
  return Notification.permission === "denied" ? "denied" : "supported";
}

/** Brave blocks push until "Use Google services for push messaging" is on. */
export function isBrave(): boolean {
  return "brave" in navigator;
}

/** VAPID key (base64url) as the bytes `applicationServerKey` takes. */
export function base64UrlToBytes(value: string): Uint8Array<ArrayBuffer> {
  const padded = value.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (value.length % 4)) % 4);
  const raw = atob(padded);
  const bytes = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  return bytes;
}

const BROWSERS: ReadonlyArray<[RegExp, string]> = [
  [/Edg\//, "Edge"],
  [/OPR\//, "Opera"],
  [/Firefox\//, "Firefox"],
  [/Chrome\//, "Chrome"],
  [/Safari\//, "Safari"],
];
const SYSTEMS: ReadonlyArray<[RegExp, string]> = [
  [/Android/, "Android"],
  [/iPhone|iPad|iPod/, "iOS"],
  [/Windows/, "Windows"],
  [/Mac OS X|Macintosh/, "macOS"],
  [/Linux/, "Linux"],
];

/** "Chrome · macOS": the device label the settings list shows. */
export function deviceLabel(ua: string): string {
  const browser = BROWSERS.find(([re]) => re.test(ua))?.[1];
  const system = SYSTEMS.find(([re]) => re.test(ua))?.[1];
  return [browser, system].filter(Boolean).join(" · ") || "Browser";
}

/** Id of the device row this browser registered, to mark it in the list. */
export function thisDeviceId(): string | null {
  try {
    return localStorage.getItem(DEVICE_KEY);
  } catch {
    return null;
  }
}

function rememberDevice(id: string | null): void {
  try {
    if (id) localStorage.setItem(DEVICE_KEY, id);
    else localStorage.removeItem(DEVICE_KEY);
  } catch {
    /* storage blocked: the list just does not mark this device */
  }
}

async function currentSubscription(): Promise<PushSubscription | null> {
  const reg = await navigator.serviceWorker.getRegistration("/");
  return reg ? reg.pushManager.getSubscription() : null;
}

/** "denied" when the user refused the permission prompt. */
export async function enablePush(publicKey: string): Promise<"enabled" | "denied"> {
  const permission = await Notification.requestPermission();
  if (permission !== "granted") return "denied";
  await navigator.serviceWorker.register(SW_URL, { scope: "/" });
  const reg = await navigator.serviceWorker.ready;
  const subscription =
    (await reg.pushManager.getSubscription()) ??
    (await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: base64UrlToBytes(publicKey),
    }));
  const keys = subscription.toJSON().keys ?? {};
  const { id } = await savePushSubscription({
    endpoint: subscription.endpoint,
    keys: { p256dh: keys.p256dh ?? "", auth: keys.auth ?? "" },
    label: deviceLabel(navigator.userAgent),
  });
  rememberDevice(id);
  return "enabled";
}

/** Turn push off in this browser: the server forgets the endpoint first, so a
 * failure there leaves the subscription intact and the list honest. */
export async function disablePushHere(): Promise<void> {
  const subscription = await currentSubscription();
  if (subscription) {
    await unsubscribePush(subscription.endpoint);
    await subscription.unsubscribe();
  }
  rememberDevice(null);
}

/** Whether this browser currently holds a push subscription. */
export async function hasPushHere(): Promise<boolean> {
  if (pushSupport() !== "supported") return false;
  try {
    return (await currentSubscription()) !== null;
  } catch {
    return false;
  }
}
