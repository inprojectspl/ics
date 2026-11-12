// HTTP plumbing of the app gateway: error shape, body limits, preconditions.
const MAX_BODY = 256 * 1024;
export const SECURITY_HEADERS = {
  "x-content-type-options": "nosniff",
  "referrer-policy": "no-referrer",
  "x-frame-options": "DENY",
  "cross-origin-opener-policy": "same-origin",
  "cross-origin-resource-policy": "same-origin",
};

export class HttpError extends Error {
  constructor(status, code, detail, extra = {}) {
    super(detail ?? code);
    this.status = status;
    this.code = code;
    Object.assign(this, extra);
  }
}

export function send(res, status, body, headers = {}) {
  const text = body === undefined ? "" : JSON.stringify(body);
  res.writeHead(status, { ...SECURITY_HEADERS, "content-type": "application/json", "cache-control": "no-store", ...headers });
  res.end(status === 204 ? undefined : text);
}

export function sendError(res, err, requestId) {
  const status = err.status ?? 500;
  const body = { code: err.code ?? "internal_error", detail: status >= 500 && !err.code ? "internal error" : err.message, request_id: requestId };
  if (err.pointer !== undefined) body.field = err.pointer || "/";
  if (err.currentRevision !== undefined) body.current_revision = err.currentRevision;
  if (status === 504 || status === 503 || err.code === "serialization_conflict") body.retryable = true;
  const headers = err.retryAfter ? { "retry-after": String(err.retryAfter) } : {};
  send(res, status, body, headers);
}

export async function readBody(req) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on("data", (c) => {
      size += c.length;
      if (size > MAX_BODY) {
        reject(new HttpError(413, "payload_too_large", "request body too large"));
        req.destroy();
        return;
      }
      chunks.push(c);
    });
    req.on("end", () => resolve(Buffer.concat(chunks)));
    req.on("error", reject);
  });
}

export async function readJson(req) {
  const raw = await readBody(req);
  if (raw.length === 0) return {};
  const type = req.headers["content-type"] ?? "";
  if (!type.startsWith("application/json")) throw new HttpError(415, "unsupported_media_type", "send application/json");
  try {
    return JSON.parse(raw.toString("utf8"));
  } catch {
    throw new HttpError(400, "invalid_json", "malformed JSON body");
  }
}

export function parseIfMatch(header) {
  if (!header) return undefined;
  const m = /^"r(\d{1,12})"$/.exec(header.trim());
  if (!m) throw new HttpError(400, "invalid_if_match", 'If-Match must look like "r7"');
  return Number(m[1]);
}

export function etag(revision) {
  return `"r${revision}"`;
}

export function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") return `{${Object.keys(value).sort().map((k) => `${JSON.stringify(k)}:${canonical(value[k])}`).join(",")}}`;
  return JSON.stringify(value);
}

