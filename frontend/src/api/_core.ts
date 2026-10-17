// Low-level fetch + URL helpers. Every `api/*` module goes through them,
// so this is the single place for the `credentials: include` policy and
// for parsing the FastAPI `detail` error.

import { getLocale } from "../lib/i18n";
import type { AssetSort } from "./types";
import { notifyDocumentChange } from "./documentChanges";

const API = import.meta.env.VITE_API_URL ?? "";

/**
 * Generic fetch wrapper. Used by every endpoint helper.
 * Exported for unit tests; runtime callers should use module-specific
 * wrappers (`api.X()`) or `postJson` for JSON-bodied POSTs.
 */
/**
 * HTTP error with the status and the server's error body kept. `message`
 * is the server `detail` or "<status> <statusText>". `code` is the stable
 * error code from `docs/api-errors.md`; UI copy is chosen by it
 * (`lib/errorMessages.ts`), never by parsing `detail`.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string | null;
  readonly code: string | null;
  /** Input field the error is about (e.g. `metadata_invalid`), when the server names one. */
  readonly field: string | null;

  constructor(
    status: number,
    detail: string | null,
    message: string,
    code: string | null = null,
    field: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.code = code;
    this.field = field;
  }
}

export async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API}${path}`, {
    ...init,
    credentials: "include",
    // The UI locale, so the server can localise what it sends (e-mails).
    headers: { "Accept-Language": getLocale(), ...init?.headers },
  });
  if (!r.ok) {
    let detail: string | null = null;
    let code: string | null = null;
    let field: string | null = null;
    try {
      const body = await r.json();
      if (body && typeof body.detail === "string") detail = body.detail;
      if (body && typeof body.code === "string") code = body.code;
      if (body && typeof body.field === "string") field = body.field;
    } catch {
      // not JSON, fall through to statusText
    }
    throw new ApiError(r.status, detail, detail ?? `${r.status} ${r.statusText}`, code, field);
  }
  notifyDocumentChange(path, init?.method);
  // 204 No Content (most DELETEs) has no body to parse.
  if (r.status === 204) return undefined as T;
  return r.json() as Promise<T>;
}

/**
 * URL-safe encode each path segment independently. The `/` separator is
 * not encoded (path structure like `Vault/Notes/page.md` is preserved).
 * Exported for tests and for the `staticUrl` helpers in `assets`/`shares`.
 */
export function encodePath(p: string): string {
  return p.split("/").map(encodeURIComponent).join("/");
}

/**
 * Appends `version=N` for an archived version preview, choosing `?` or `&`
 * from the path. Omitted for the current version, so common URLs stay
 * unchanged in logs and caches.
 */
export function withVersion(path: string, version?: number): string {
  if (!version) return path;
  return `${path}${path.includes("?") ? "&" : "?"}version=${version}`;
}

/** `init` adds fetch options, e.g. `keepalive` for a request that must
 * survive leaving the page. */
export function postJson<T>(path: string, body: unknown, init?: RequestInit): Promise<T> {
  return req<T>(path, {
    ...init,
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function patchJson<T>(path: string, body: unknown): Promise<T> {
  return req<T>(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function putJson<T>(path: string, body: unknown): Promise<T> {
  return req<T>(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** `<lead>sort=<key>&order=<dir>` for the asset list endpoints; "" without a sort. */
export const sortQuery = (sort: AssetSort | undefined, lead: "?" | "&") =>
  sort ? `${lead}sort=${sort.key}&order=${sort.order}` : "";
