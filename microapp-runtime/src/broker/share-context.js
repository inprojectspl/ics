// Copyable app addresses: the `ics_share` URL parameter and the shared
// share_context.js bootstrap (source in ICS, backend/app/static), injected
// into every HTML page of an app origin. Mirrors backend/app/services/
// share_context.py; contract in docs/copyable-addresses.md.
import { SECURITY_HEADERS } from "./http.js";

const SHARE_PARAM = "ics_share";
export const TOKEN_RE = /^[A-Za-z0-9_-]{16,128}$/;
export const ENTRY_COOKIE = "__Host-ics-app-entry";
/** Value format of ENTRY_COOKIE (a random launch id). */
export const LAUNCH_RE = /^[A-Za-z0-9_-]{8,32}$/;
export const SCRIPT_PATH = "/__ics/share-context.js";
const MAX_TARGET_LEN = 2048;
const RESERVED = ["__ics/", "api/"];
const SCRIPT_TTL_MS = 5 * 60 * 1000;

function decodePart(text) {
  try {
    return decodeURIComponent(text.replace(/\+/g, " "));
  } catch {
    return text;
  }
}

const paramName = (part) => decodePart(part.split("=", 1)[0]);

/** `{ state: "none" | "one" | "invalid", token }` of a query string. */
export function readToken(search) {
  const query = search.startsWith("?") ? search.slice(1) : search;
  const found = query
    .split("&")
    .filter((part) => part && paramName(part) === SHARE_PARAM)
    .map((part) => (part.includes("=") ? decodePart(part.slice(part.indexOf("=") + 1)) : ""));
  if (found.length === 0) return { state: "none", token: null };
  if (found.length > 1 || !TOKEN_RE.test(found[0])) return { state: "invalid", token: null };
  return { state: "one", token: found[0] };
}

/** `query` with exactly one `ics_share=token` at the end (none for null). */
export function withToken(query, token) {
  const parts = query.split("&").filter((part) => part && paramName(part) !== SHARE_PARAM);
  if (token) parts.push(`${SHARE_PARAM}=${token}`);
  return parts.join("&");
}

function unsafe(text) {
  return text.includes("\\") || [...text].some((c) => c.charCodeAt(0) < 0x20 || c.charCodeAt(0) === 0x7f);
}

/** An app page as `path?query` relative to `/`, without the token, or null
 * for anything that could leave the app's pages (see clean_target in ICS),
 * including the gateway's own `/__ics/` and `/api/` routes. */
export function cleanTarget(to) {
  if (!to || to.length > MAX_TARGET_LEN || to.includes("#") || unsafe(to)) return null;
  const q = to.indexOf("?");
  const path = q < 0 ? to : to.slice(0, q);
  const once = decodePart(path);
  for (const form of [path, once, decodePart(once)]) {
    const segments = form.split("/");
    if (unsafe(form) || form.startsWith("/") || segments.some((s) => s === "." || s === "..") || segments.slice(0, -1).includes("")) return null;
    if (RESERVED.some((prefix) => form.toLowerCase().startsWith(prefix))) return null;
  }
  const query = withToken(q < 0 ? "" : to.slice(q + 1), null);
  return query ? `${path}?${query}` : path;
}

/** Local `/path?query` of a checked target with the token. */
export function targetPath(target, token) {
  const q = target.indexOf("?");
  const query = withToken(q < 0 ? "" : target.slice(q + 1), token);
  return `/${q < 0 ? target : target.slice(0, q)}${query ? `?${query}` : ""}`;
}

/** A page of the app (no extension or .html), not a file it loads. */
export function isDocumentPath(pathname) {
  if (pathname.startsWith("/__ics/") || pathname.startsWith("/api/")) return false;
  const last = pathname.slice(pathname.lastIndexOf("/") + 1);
  const dot = last.lastIndexOf(".");
  const ext = dot < 0 ? "" : last.slice(dot + 1).toLowerCase();
  return ext === "" || ext === "html" || ext === "htm";
}

const escapeHtml = (text) =>
  String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#x27;" })[c]);

/** The bootstrap element; keys become `data-*` attributes (assetId -> data-asset-id). */
export function scriptTag(attrs) {
  const data = Object.entries(attrs)
    .filter(([, value]) => value !== undefined && value !== null)
    .map(([key, value]) => ` data-${key.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`)}="${escapeHtml(value)}"`)
    .join("");
  return `<script src="${SCRIPT_PATH}"${data}></script>`;
}

// ---------- head injection (mirror of head_insert_at in ICS) ----------

const RAW_TEXT_CLOSE = { title: /<\/title\s*>/i, style: /<\/style\s*>/i };
// The insertion point is in the head: the scan reads the start of the page
// and the whole of it only when that start is all head (whitespace to its end).
const SCAN_BYTES = 64 * 1024;
const HEAD_VOID = new Set(["meta", "link", "base"]);
const CHARSET_RE = /charset\s*=|http-equiv\s*=\s*["']?content-type/i;
const TAG_RE = /<(\/?)([A-Za-z][A-Za-z0-9-]*)/y;

function tagEnd(text, k) {
  let quote = "";
  for (let i = k; i < text.length; i++) {
    const c = text[i];
    if (quote) {
      if (c === quote) quote = "";
    } else if (c === '"' || c === "'") quote = c;
    else if (c === ">") return i + 1;
  }
  return -1;
}

/** Where the bootstrap goes: right after the charset declaration when it
 * comes first, else before the first script or other content, never inside
 * a comment or script text. Byte offset into `buf`. */
export function headInsertAt(buf) {
  const at = scanHead(buf.toString("latin1", 0, SCAN_BYTES));
  // Every other answer is a token boundary inside the start, which is valid.
  return at < SCAN_BYTES || buf.length <= SCAN_BYTES ? at : scanHead(buf.toString("latin1"));
}

// latin1 keeps one character per byte, so offsets are byte offsets.
function scanHead(text) {
  let i = text.startsWith("\u00ef\u00bb\u00bf") ? 3 : 0;
  for (;;) {
    while (i < text.length && " \t\r\n\f".includes(text[i])) i++;
    if (i >= text.length || text[i] !== "<") return i;
    if (text.startsWith("<!--", i)) {
      const close = text.indexOf("-->", i + 4);
      if (close < 0) return i;
      i = close + 3;
      continue;
    }
    if (text.startsWith("<!", i) || text.startsWith("<?", i)) {
      const close = text.indexOf(">", i);
      if (close < 0) return i;
      i = close + 1;
      continue;
    }
    TAG_RE.lastIndex = i;
    const m = TAG_RE.exec(text);
    if (!m || m[1]) return i;
    const name = m[2].toLowerCase();
    const end = tagEnd(text, TAG_RE.lastIndex);
    if (end < 0) return i;
    if (name === "html" || name === "head") i = end;
    else if (HEAD_VOID.has(name)) {
      if (name === "meta" && CHARSET_RE.test(text.slice(i, end))) return end;
      i = end;
    } else if (name in RAW_TEXT_CLOSE) {
      const close = RAW_TEXT_CLOSE[name].exec(text.slice(end));
      if (!close) return i;
      i = end + close.index + close[0].length;
    } else return i;
  }
}

export function injectHead(buf, snippet) {
  const at = headInsertAt(buf);
  return Buffer.concat([buf.subarray(0, at), Buffer.from(snippet, "ascii"), buf.subarray(at)]);
}

// ---------- entry page ----------

/** Served instead of an app page without a session: no app content, only the
 * bootstrap, which resumes the visit through the link in the address or the
 * tab's context, else starts the usual ICS sign-in. */
export function recoveryPage(res, target, url, status = 401) {
  const to = cleanTarget(url.pathname.slice(1) + url.search) ?? "";
  const login = `/__ics/login?to=${encodeURIComponent(to)}`;
  const tag = scriptTag({
    assetId: target.assetHex,
    kind: "micro_application",
    scope: "/",
    entryMode: "recover",
    recoverShare: "/__ics/share?token={token}&to={to}",
    recoverLogin: "/__ics/login?to={to}",
  });
  const body =
    `<!doctype html><html><head><meta charset="utf-8"><meta name="referrer" content="no-referrer">${tag}` +
    `<noscript><meta http-equiv="refresh" content="0;url=${escapeHtml(login)}"></noscript></head><body></body></html>`;
  res.writeHead(status, {
    ...SECURITY_HEADERS,
    "content-type": "text/html; charset=utf-8",
    "content-security-policy": "default-src 'none'; script-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    "cache-control": "no-store",
  });
  res.end(body);
}

/** The bootstrap source, fetched from ICS and kept for a few minutes. */
export class ShareContextScript {
  constructor(ics, ttlMs = SCRIPT_TTL_MS) {
    this.ics = ics;
    this.ttlMs = ttlMs;
    this.cached = null;
    this.pending = null;
  }

  /** `{ body, etag }` */
  async get() {
    if (this.cached && Date.now() - this.cached.at < this.ttlMs) return this.cached;
    this.pending ??= this.ics
      .shareContextScript()
      .then((script) => {
        this.cached = { ...script, at: Date.now() };
        return this.cached;
      })
      .catch((err) => {
        // ICS away for a moment: the last copy is still the right one.
        if (this.cached) return this.cached;
        throw err;
      })
      .finally(() => {
        this.pending = null;
      });
    return this.pending;
  }
}
