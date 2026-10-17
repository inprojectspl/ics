import { useEffect, useState } from "react";
import { api } from "../api";
import { statusCode } from "./apiError";

/** `resolving`: asking the backend what to do; `dead-end`: there is no way
 * in and a message must be shown; `unresolved`: the resolver did not help
 * (outage, rate limit), so the regular error takes over. `idle` means there
 * is no error and nothing to rescue. */
export type EntryFallbackState = "idle" | "resolving" | "dead-end" | "unresolved";
type Settled = "dead-end" | "unresolved";

/** 401 = no session, 404 = no role (the backend does not reveal that the
 * asset exists). Anything else is an outage, not an access problem. */
function isAccessError(status: number | null): boolean {
  return status === 401 || status === 404;
}

function isCurrentLocation(url: string): boolean {
  const target = new URL(url, window.location.origin);
  return (
    target.origin === window.location.origin &&
    target.pathname === window.location.pathname &&
    target.hash === window.location.hash
  );
}

/**
 * For a `/v/<slug>` link opened without a role on the asset: asks the entry
 * resolver for a way in and follows it. Uses `location.replace` because the
 * address being left does not work for this person.
 */
export function useEntryFallback(
  slug: string,
  errorStatus: number | null,
): EntryFallbackState {
  // The outcome is stored with the (slug, status) it was resolved for, so a
  // new error reads as "resolving" until its own answer arrives and a cleared
  // error reads as "idle", without resetting state from the effect.
  const key = isAccessError(errorStatus) ? `${slug}:${errorStatus}` : null;
  const [outcome, setOutcome] = useState<{ key: string; state: Settled } | null>(null);

  useEffect(() => {
    if (key === null) return;
    let cancelled = false;
    const settle = (state: Settled) => setOutcome({ key, state });
    (async () => {
      try {
        const entry = await api.getEntry(slug);
        if (cancelled) return;
        // The SPA router owns the login route, so it is built here; the
        // backend only returns the slug to come back to. `view` after a
        // `/doc` error means the resolver and the reader disagree about
        // access (the session expired between the two requests), so there
        // is nowhere to go.
        const target =
          entry.action === "login"
            ? `/#login?next=${encodeURIComponent(`/v/${entry.slug}`)}`
            : entry.action === "redirect"
              ? entry.url
              : null;
        // The reader may already be mounted at the address the resolver
        // would point to (full view under `/s/<token>`); redirecting there
        // would cause a reload loop.
        if (!target || isCurrentLocation(target)) {
          settle("dead-end");
          return;
        }
        window.location.replace(target);
      } catch (e) {
        if (cancelled) return;
        // Only 404 means "no way in". A 429 from the rate limit (shared
        // office IP, a burst of clicks) or a 5xx is an outage, so the
        // regular error message takes over instead of claiming the
        // document is not shared.
        settle(statusCode(e) === 404 ? "dead-end" : "unresolved");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [slug, key]);

  if (key === null) return "idle";
  return outcome?.key === key ? outcome.state : "resolving";
}
