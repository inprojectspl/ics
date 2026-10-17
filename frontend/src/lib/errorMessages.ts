/**
 * The only mapping from server error `code` (`docs/api-errors.md`) to UI
 * copy: catalogue entry `error.<code>`; without one, callers use status copy.
 */
import { hasMessage, t } from "./i18n";

/** UI message for an API error code, or undefined when the code has none. */
export function messageForCode(code: string | null | undefined): string | undefined {
  if (!code) return undefined;
  const key = `error.${code}`;
  return hasMessage(key) ? t(key) : undefined;
}

// Mirrors `_STATUS_CODES` in backend/app/errors.py.
const STATUS_CODES: Readonly<Record<number, string>> = {
  400: "bad_request",
  401: "unauthorized",
  403: "forbidden",
  404: "not_found",
  405: "method_not_allowed",
  409: "conflict",
  410: "gone",
  413: "payload_too_large",
  415: "unsupported_media_type",
  422: "validation_error",
  429: "rate_limited",
};

/** Generic UI message for an HTTP status, or undefined for unknown ones. */
export function messageForStatus(status: number): string | undefined {
  return messageForCode(status >= 500 ? "server_error" : STATUS_CODES[status]);
}
