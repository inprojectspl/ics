// Browser SDK served at /__ics/sdk.js on every app origin. It adds the
// headers the gateway requires (CSRF token, release, data generation,
// If-Match, Idempotency-Key) so app code only deals with data.
export const SDK_SOURCE = String.raw`(function () {
  "use strict";
  let sessionPromise = null;
  function newKey() {
    const b = new Uint8Array(16);
    crypto.getRandomValues(b);
    return Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
  }
  class IcsApiError extends Error {
    constructor(status, body) {
      super((body && (body.detail || body.code)) || "HTTP " + status);
      this.status = status;
      this.code = body && body.code;
      this.field = body && body.field;
      this.body = body;
    }
  }
  async function session() {
    if (!sessionPromise) {
      sessionPromise = fetch("/api/v1/session", { credentials: "same-origin" }).then(async (r) => {
        const body = await r.json().catch(() => null);
        if (!r.ok) {
          sessionPromise = null;
          throw new IcsApiError(r.status, body);
        }
        return body;
      });
    }
    return sessionPromise;
  }
  async function request(method, path, { body, ifMatch, idempotencyKey, query } = {}) {
    const s = await session();
    const headers = { "x-ics-csrf": s.csrfToken, "x-ics-release": s.app.release, "x-ics-data-generation": String(s.app.dataGeneration) };
    if (body !== undefined) headers["content-type"] = "application/json";
    if (ifMatch !== undefined && ifMatch !== null) headers["if-match"] = '"r' + ifMatch + '"';
    if (idempotencyKey) headers["idempotency-key"] = idempotencyKey;
    let url = path;
    if (query) {
      const q = new URLSearchParams();
      for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
      const text = q.toString();
      if (text) url += "?" + text;
    }
    const r = await fetch(url, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), credentials: "same-origin" });
    if (r.status === 204) return null;
    const data = await r.json().catch(() => null);
    if (!r.ok) {
      if (r.status === 409 && data && (data.code === "release_changed" || data.code === "data_generation_changed")) sessionPromise = null;
      throw new IcsApiError(r.status, data);
    }
    return data;
  }
  function collection(name) {
    const base = "/api/v1/collections/" + encodeURIComponent(name);
    return {
      list: (query) => request("GET", base, { query }),
      get: (id) => request("GET", base + "/" + encodeURIComponent(id)),
      create: (data, opts = {}) => request("POST", base, { body: data, idempotencyKey: opts.idempotencyKey || newKey() }),
      update: (id, revision, patch, opts = {}) => request("PATCH", base + "/" + encodeURIComponent(id), { body: patch, ifMatch: revision, idempotencyKey: opts.idempotencyKey }),
      remove: (id, revision, opts = {}) => request("DELETE", base + "/" + encodeURIComponent(id), { ifMatch: revision, idempotencyKey: opts.idempotencyKey || newKey() }),
    };
  }
  function call(method, path, opts = {}) {
    const needsKey = method !== "GET" && !opts.idempotencyKey;
    return request(method, "/api" + path, { ...opts, idempotencyKey: needsKey ? newKey() : opts.idempotencyKey });
  }
  window.ics = Object.freeze({ session, collection, call, newKey, IcsApiError });
})();
`;
