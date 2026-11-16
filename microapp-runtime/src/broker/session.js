// Host-bound application sessions. The cookie is host-only (`__Host-`), signed
// by the broker and bound to one asset, environment and host; it is useless
// on another app origin, in the main ICS API and in MCP.
import crypto from "node:crypto";

export const SESSION_COOKIE = "__Host-ics-app";
export const START_COOKIE = "__Host-ics-app-start";
const SESSION_TTL_S = 8 * 3600;

function sign(secret, text) {
  return crypto.createHmac("sha256", secret).update(text).digest("base64url");
}

function safeEqual(a, b) {
  const x = Buffer.from(a);
  const y = Buffer.from(b);
  return x.length === y.length && crypto.timingSafeEqual(x, y);
}

export function parseCookies(header) {
  const out = {};
  for (const part of (header ?? "").split(";")) {
    const i = part.indexOf("=");
    if (i < 0) continue;
    const k = part.slice(0, i).trim();
    if (k && !(k in out)) out[k] = part.slice(i + 1).trim();
  }
  return out;
}

export const SHARE_SESSION_TTL_S = 30 * 24 * 3600;

export function issueSession(secret, { userId, assetHex, environment, host, shareId = null }) {
  // A share-link visitor keeps one anonymous identity for a month, so their
  // own records (votes, scores) stay theirs on the next visit.
  const ttl = shareId ? SHARE_SESSION_TTL_S : SESSION_TTL_S;
  const payload = { sid: crypto.randomBytes(16).toString("base64url"), uid: userId, a: assetHex, e: environment, h: host, exp: Math.floor(Date.now() / 1000) + ttl };
  if (shareId) payload.sh = shareId;
  const body = Buffer.from(JSON.stringify(payload)).toString("base64url");
  return { value: `${body}.${sign(secret, `s:${body}`)}`, payload };
}

export function readSession(secret, cookieValue, { assetHex, environment, host }) {
  if (!cookieValue) return null;
  const [body, sig] = cookieValue.split(".");
  if (!body || !sig || !safeEqual(sig, sign(secret, `s:${body}`))) return null;
  let payload;
  try {
    payload = JSON.parse(Buffer.from(body, "base64url").toString());
  } catch {
    return null;
  }
  if (payload.a !== assetHex || payload.e !== environment || payload.h !== host) return null;
  if (!payload.exp || payload.exp < Date.now() / 1000) return null;
  return payload;
}

export function csrfToken(secret, session) {
  return sign(secret, `csrf:${session.sid}:${session.h}`);
}

export function checkCsrf(secret, session, token) {
  return typeof token === "string" && safeEqual(token, csrfToken(secret, session));
}

export function newStartNonce() {
  return crypto.randomBytes(24).toString("base64url");
}

export function stateOf(nonce) {
  return crypto.createHash("sha256").update(nonce).digest("base64url");
}

export function cookie(name, value, { maxAge } = {}) {
  const parts = [`${name}=${value}`, "Path=/", "Secure", "HttpOnly", "SameSite=Lax"];
  if (maxAge !== undefined) parts.push(`Max-Age=${maxAge}`);
  return parts.join("; ");
}
