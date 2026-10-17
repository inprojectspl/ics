// One live notification stream per browser (ADR-0023, section 6): tabs elect
// a leader with the Web Locks API, the leader holds the EventSource and
// relays every event over a BroadcastChannel. When the leader tab goes
// away, the lock passes to a waiting tab, which opens its own stream.
import { STREAM_URL } from "../../api/notifications";
import type { NotificationStreamEvent } from "../../api/notificationTypes";

const LOCK_NAME = "ics-notifications";
const CHANNEL_NAME = "ics-notifications";
/** A closed source (HTTP error, lost session) does not reconnect by itself. */
export const STREAM_RETRY_MS = 30_000;
const EVENT_TYPES = ["notification", "sync", "reset"] as const;
// EventSource.OPEN and CLOSED; test stubs do not carry the static constants.
const OPEN = 1;
const CLOSED = 2;

type Listener = (event: NotificationStreamEvent) => void;

function parseEvent(type: (typeof EVENT_TYPES)[number], raw: unknown): NotificationStreamEvent | null {
  if (type === "reset") return { type };
  try {
    const data: unknown = JSON.parse(String(raw));
    if (typeof data !== "object" || data === null || !("unread" in data)) return null;
    if (typeof data.unread !== "number") return null;
    if (type === "sync") return { type, data } as NotificationStreamEvent;
    return "item" in data && data.item ? ({ type, data } as NotificationStreamEvent) : null;
  } catch {
    return null;
  }
}

function isStreamEvent(value: unknown): value is NotificationStreamEvent {
  if (typeof value !== "object" || value === null || !("type" in value)) return false;
  return value.type === "notification" || value.type === "sync" || value.type === "reset";
}

export interface StreamHandle {
  close: () => void;
  /** Events are arriving: this tab's stream is open, or another tab holds
   * the stream and relays it. */
  live: () => boolean;
}

/**
 * Start receiving live events. Without Web Locks (or BroadcastChannel)
 * every tab keeps its own stream.
 */
export function openNotificationStream(
  onEvent: Listener,
  onLive?: (live: boolean) => void,
): StreamHandle {
  let closed = false;
  let source: EventSource | null = null;
  let retry: ReturnType<typeof setTimeout> | undefined;
  let release: (() => void) | undefined;
  const channel = typeof BroadcastChannel === "function" ? new BroadcastChannel(CHANNEL_NAME) : null;
  const locks = typeof navigator === "undefined" ? undefined : navigator.locks;
  const shared = Boolean(locks && channel);
  const abort = new AbortController();
  let follower = false;
  let reported = false;
  const live = () => !closed && (follower || source?.readyState === OPEN);
  const report = () => {
    const now = live();
    if (now === reported) return;
    reported = now;
    onLive?.(now);
  };

  const emit = (event: NotificationStreamEvent) => {
    onEvent(event);
    if (shared) channel?.postMessage(event);
  };

  const connect = () => {
    if (closed || typeof EventSource !== "function") return;
    const es = new EventSource(STREAM_URL, { withCredentials: true });
    source = es;
    report();
    for (const type of EVENT_TYPES) {
      es.addEventListener(type, (msg) => {
        const event = parseEvent(type, (msg as MessageEvent).data);
        if (event) emit(event);
      });
    }
    es.onopen = report;
    es.onerror = () => {
      report();
      if (closed || es.readyState !== CLOSED) return;
      es.close();
      source = null;
      retry = setTimeout(() => {
        // A new source has no Last-Event-ID, so what was missed is refetched.
        emit({ type: "reset" });
        connect();
      }, STREAM_RETRY_MS);
    };
  };

  const lead = () =>
    new Promise<void>((resolve) => {
      release = resolve;
      connect();
    });

  if (locks && channel) {
    channel.onmessage = (e: MessageEvent) => {
      if (!closed && isStreamEvent(e.data)) onEvent(e.data);
    };
    locks
      .request(LOCK_NAME, { ifAvailable: true }, (lock) => {
        if (closed) return undefined;
        if (lock) return lead();
        follower = true;
        report();
        // Another tab holds the stream: wait for it, then take over. Events
        // between its close and our open reached no one, hence the reset.
        locks
          .request(LOCK_NAME, { signal: abort.signal }, () => {
            if (closed) return undefined;
            follower = false;
            onEvent({ type: "reset" });
            return lead();
          })
          .catch(() => undefined);
        return undefined;
      })
      .catch(() => undefined);
  } else {
    connect();
  }

  return {
    close: () => {
      closed = true;
      clearTimeout(retry);
      source?.close();
      source = null;
      release?.();
      abort.abort();
      channel?.close();
      report();
    },
    live,
  };
}
