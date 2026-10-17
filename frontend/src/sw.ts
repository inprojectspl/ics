// Service worker for Web Push (ADR-0023, section 7), served as `/sw.js`.
// Built on its own by the `serviceWorker` plugin in vite.config.ts: a
// classic script, so no imports or exports here. No offline caching.

// One block keeps these declarations out of the global scope the rest of
// `src` type-checks against (the file is a script, not a module).
{
  // Only the parts of the worker scope this file uses; the project compiles
  // against the DOM lib, not WebWorker.
  interface SwClient {
    url: string;
    focused: boolean;
    focus(): Promise<SwClient>;
    navigate(url: string): Promise<SwClient | null>;
    postMessage(message: unknown): void;
  }
  interface ExtendableEvent extends Event {
    waitUntil(promise: Promise<unknown>): void;
  }
  interface PushEvent extends ExtendableEvent {
    data: { json(): unknown } | null;
  }
  interface NotificationClickEvent extends ExtendableEvent {
    notification: Notification;
  }
  interface SwScope {
    location: Location;
    clients: {
      matchAll(options: { type: "window"; includeUncontrolled: boolean }): Promise<SwClient[]>;
      openWindow(url: string): Promise<SwClient | null>;
      claim(): Promise<void>;
    };
    registration: {
      showNotification(title: string, options: NotificationOptions & { renotify?: boolean }): Promise<void>;
    };
    skipWaiting(): Promise<void>;
    addEventListener(type: "install" | "activate", fn: (e: ExtendableEvent) => void): void;
    addEventListener(type: "push", fn: (e: PushEvent) => void): void;
    addEventListener(type: "notificationclick", fn: (e: NotificationClickEvent) => void): void;
  }

  interface PushPayload {
    title: string;
    body: string;
    url: string;
    tag: string;
  }

  const sw = self as unknown as SwScope;

  function parsePayload(event: PushEvent): PushPayload | null {
    try {
      const data = event.data?.json() as Partial<PushPayload> | undefined;
      if (!data || typeof data.title !== "string") return null;
      return { title: data.title, body: data.body ?? "", url: data.url ?? "/notifications", tag: data.tag ?? "" };
    } catch {
      return null;
    }
  }

  /** Same-origin path only: the payload must not send anyone elsewhere. */
  function safeUrl(url: string): string {
    try {
      const target = new URL(url, sw.location.origin);
      return target.origin === sw.location.origin ? target.href : sw.location.origin;
    } catch {
      return sw.location.origin;
    }
  }

  async function windows(): Promise<SwClient[]> {
    return sw.clients.matchAll({ type: "window", includeUncontrolled: true });
  }

  async function onPush(payload: PushPayload): Promise<void> {
    // A focused ICS tab already shows the event (live stream and toast).
    const focused = (await windows()).find((c) => c.focused);
    if (focused) {
      // Same string as SW_PUSH_MESSAGE in lib/notifications/useNotificationStream.ts.
      focused.postMessage({ type: "ics-push", payload });
      return;
    }
    await sw.registration.showNotification(payload.title, {
      body: payload.body,
      tag: payload.tag || undefined,
      renotify: Boolean(payload.tag),
      // Android and Windows ignore SVG notification icons.
      icon: "/icons/icon-192.png",
      data: { url: payload.url },
    });
  }

  async function onClick(url: string): Promise<void> {
    const target = safeUrl(url);
    const existing = (await windows()).find((c) => new URL(c.url).origin === sw.location.origin);
    if (existing) {
      const client = await existing.focus();
      try {
        await client.navigate(target);
        return;
      } catch {
        // Only a tab this worker controls can be navigated; open a new one.
      }
    }
    await sw.clients.openWindow(target);
  }

  sw.addEventListener("install", () => void sw.skipWaiting());
  sw.addEventListener("activate", (event) => event.waitUntil(sw.clients.claim()));

  sw.addEventListener("push", (event) => {
    const payload = parsePayload(event);
    if (payload) event.waitUntil(onPush(payload));
  });

  sw.addEventListener("notificationclick", (event) => {
    event.notification.close();
    const data = event.notification.data as { url?: unknown } | null;
    event.waitUntil(onClick(typeof data?.url === "string" ? data.url : "/notifications"));
  });
}
