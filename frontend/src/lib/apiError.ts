import { ApiError } from "../api/_core";
import { messageForCode, messageForStatus } from "./errorMessages";

/**
 * User-facing message for an error thrown by `req()`. A known server `code`
 * wins; `detail` is developer text and never shown. Otherwise status copy,
 * or the caller's `fallback` when the server sent a detail.
 */
export function formatApiError(err: unknown, fallback?: string): string {
  const byCode = err instanceof ApiError ? messageForCode(err.code) : undefined;
  if (byCode) return byCode;
  const status = statusCode(err);
  const byStatus = status === null ? undefined : messageForStatus(status);
  const explained = err instanceof ApiError && err.detail !== null;
  if (byStatus && !explained) return byStatus;
  return fallback || byStatus || (err instanceof Error ? err.message : String(err));
}

/** Stable server `code` of an API error, or null for any other failure. */
export function errorCode(err: unknown): string | null {
  return err instanceof ApiError ? err.code : null;
}

export function statusCode(err: unknown): number | null {
  // `ApiError` carries the status directly. The regex stays for errors
  // from outside `req()` (and tests that build a bare `Error("404 ...")`);
  // it is not enough alone, since a server `detail` has no status in it.
  if (err instanceof ApiError) return err.status;
  const msg = err instanceof Error ? err.message : String(err);
  const m = msg.match(/^(\d{3})\b/);
  return m ? Number(m[1]) : null;
}
