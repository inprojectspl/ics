/** A same-origin path to return to after signing in, or undefined for anything
 * else, so a crafted link cannot redirect off the app. */
export function safeNextPath(next: string | null | undefined): string | undefined {
  if (!next || !next.startsWith("/") || next.startsWith("//")) return undefined;
  try {
    const target = new URL(next, window.location.origin);
    return target.origin === window.location.origin ? target.pathname + target.search : undefined;
  } catch {
    return undefined;
  }
}
