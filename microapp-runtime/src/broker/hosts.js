// Which application a request host names. The long `a-<hex>-<env>` label of
// earlier releases carries the asset id and a configured alias names it; a
// short label is random and says nothing by itself, so ICS maps it. A host
// only identifies the app: the host-bound session, the launch code and the
// ICS authorization of every request still decide what anyone may do.
const LEGACY_RE = /^a-([0-9a-f]{32})-(prod)$/;
// The readable alphabet of ICS slugs (backend/app/slug.py), 8 characters.
const SHORT_RE = /^[abcdefghjkmnpqrstuvwxyz23456789]{8}$/;
const HEX_RE = /^[0-9a-f]{32}$/;
const CACHE_MAX = 4096;
const MISS_TTL_MS = 10_000;

export class HostResolver {
  constructor({ config, ics, now = Date.now }) {
    this.config = config;
    this.ics = ics;
    this.now = now;
    // A name is never given to another app, so a known mapping never goes
    // stale; a deleted app is refused by the authorization, not here.
    this.known = new Map();
    this.misses = new Map();
    // One ICS call per host however many requests of a page arrive at once.
    this.pending = new Map();
  }

  async resolve(rawHost) {
    const host = (rawHost ?? "").toLowerCase();
    const aliasHex = this.config.aliases?.get(host);
    if (aliasHex) return { host, assetHex: aliasHex, environment: "prod", alias: true, icsBaseUrl: this.config.publicIcsUrl ?? undefined };
    const suffix = `.${this.config.hostSuffix}`;
    if (!host.endsWith(suffix)) return null;
    const label = host.slice(0, -suffix.length);
    const legacy = LEGACY_RE.exec(label);
    if (legacy) return { host, assetHex: legacy[1], environment: legacy[2] };
    return SHORT_RE.test(label) ? this.#lookup(host) : null;
  }

  async #lookup(host) {
    const hit = this.known.get(host);
    if (hit) {
      this.known.delete(host);
      this.known.set(host, hit);
      return { host, ...hit };
    }
    const missAt = this.misses.get(host);
    if (missAt !== undefined && this.now() - missAt < MISS_TTL_MS) return null;
    let pending = this.pending.get(host);
    if (!pending) {
      pending = this.#ask(host).finally(() => this.pending.delete(host));
      this.pending.set(host, pending);
    }
    const entry = await pending;
    return entry ? { host, ...entry } : null;
  }

  async #ask(host) {
    let found;
    try {
      found = await this.ics.resolveHost(host);
    } catch (err) {
      if (err.status !== 404) throw err;
      remember(this.misses, host, this.now());
      return null;
    }
    if (found?.host !== host || !HEX_RE.test(found.asset_hex ?? "") || found.environment !== "prod") return null;
    const entry = { assetHex: found.asset_hex, environment: found.environment };
    remember(this.known, host, entry);
    this.misses.delete(host);
    return entry;
  }
}

function remember(map, key, value) {
  map.set(key, value);
  while (map.size > CACHE_MAX) map.delete(map.keys().next().value);
}
