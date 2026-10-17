import { useSyncExternalStore } from "react";

// Whether this tab gets live events (`stream.ts`), for the queries that
// can skip refetching while the stream keeps them current.
let live = false;
const listeners = new Set<() => void>();

export function setStreamLive(next: boolean): void {
  if (next === live) return;
  live = next;
  for (const fn of listeners) fn();
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function useStreamLive(): boolean {
  return useSyncExternalStore(subscribe, () => live, () => false);
}
