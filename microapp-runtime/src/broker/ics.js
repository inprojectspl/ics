// Client of the ICS internal API (private network only, service token).
// The broker asks ICS on every request: no permission cache, and a failed
// check blocks the operation.
export class IcsClient {
  constructor({ baseUrl, serviceToken, timeoutMs = 3000 }) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.token = serviceToken;
    this.timeoutMs = timeoutMs;
  }

  async #call(method, path, body, { raw = false } = {}) {
    const res = await fetch(`${this.baseUrl}${path}`, {
      method,
      headers: {
        "x-ics-service-token": this.token,
        ...(body !== undefined ? { "content-type": "application/json" } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(this.timeoutMs),
    }).catch((err) => {
      throw Object.assign(new Error(`ICS unreachable: ${err.message}`), { status: 503, code: "ics_unavailable" });
    });
    if (raw) return res;
    const text = await res.text();
    const data = text ? JSON.parse(text) : null;
    if (!res.ok) {
      throw Object.assign(new Error(data?.detail ?? `ICS ${res.status}`), { status: res.status >= 500 ? 503 : res.status, code: data?.code ?? "ics_error" });
    }
    return data;
  }

  authorize(assetHex, environment, userId, shareId = null, shareToken = null) {
    return this.#call("POST", "/api/internal/microapps/authorize", { asset: assetHex, environment, user_id: userId, share_id: shareId, share_token: shareToken });
  }

  async shareContextScript() {
    const res = await this.#call("GET", "/api/internal/microapps/share-context.js", undefined, { raw: true });
    if (!res.ok) throw Object.assign(new Error(`ICS ${res.status}`), { status: 503, code: "ics_error" });
    return { body: Buffer.from(await res.arrayBuffer()), etag: res.headers.get("etag") ?? null };
  }

  resolveHost(host) {
    return this.#call("POST", "/api/internal/microapps/hosts/resolve", { host });
  }

  exchangeLaunch(code, host, state) {
    return this.#call("POST", "/api/internal/microapps/launch/exchange", { code, host, state });
  }

  bundle(releaseId) {
    return this.#call("GET", `/api/internal/microapps/releases/${encodeURIComponent(releaseId)}/bundle`);
  }

  async publicFile(releaseId, path) {
    const res = await this.#call("GET", `/api/internal/microapps/releases/${encodeURIComponent(releaseId)}/public?path=${encodeURIComponent(path)}`, undefined, { raw: true });
    if (res.status === 404) return null;
    if (!res.ok) throw Object.assign(new Error(`ICS ${res.status}`), { status: 503, code: "ics_error" });
    return { bytes: Buffer.from(await res.arrayBuffer()), type: res.headers.get("content-type") ?? "application/octet-stream" };
  }

  binding(assetId, environment) {
    return this.#call("GET", `/api/internal/microapps/environments/${assetId}/${environment}/binding`);
  }

  report(payload) {
    return this.#call("POST", "/api/internal/microapps/report", payload);
  }
}
