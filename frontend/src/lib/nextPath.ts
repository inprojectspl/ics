/** A same-origin path to return to after signing in, or undefined for anything
 * else, so a crafted link cannot redirect off the app. */
export function safeNextPath(next: string | null | undefined): string | undefined {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.includes("\\")) return undefined;
  if ([...next].some((char) => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127)) return undefined;
  try {
    const target = new URL(next, window.location.origin);
    // Dot-segment normalization must not turn a path into a network-path URL
    // when the result is later passed to location.assign.
    return target.origin === window.location.origin && !target.pathname.startsWith("//")
      ? target.pathname + target.search
      : undefined;
  } catch {
    return undefined;
  }
}
