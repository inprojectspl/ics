// Browser SDK served at /__ics/sdk.js on every app origin. It adds the
// headers the gateway requires (CSRF token, release, data generation,
// If-Match, Idempotency-Key) so app code only deals with data, and keeps the
// page's one realtime socket (ADR-0032), opened only when first needed.
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
  const realtime = (function () {
    const rooms = new Map();
    const watchers = new Map();
    const events = { status: new Set(), error: new Set() };
    let ws = null;
    let status = "closed";
    let retry = null;
    let attempt = 0;
    let opened = false;
    let stopped = false;
    let heard = 0;
    let beat = null;
    function emit(set, ...args) {
      for (const fn of [...set]) {
        try {
          fn(...args);
        } catch (e) {
          setTimeout(() => { throw e; });
        }
      }
    }
    function setStatus(s) {
      if (s === status) return;
      status = s;
      emit(events.status, s);
    }
    function send(msg) {
      if (!ws || ws.readyState !== 1) return false;
      ws.send(JSON.stringify(msg));
      return true;
    }
    const needed = () => rooms.size > 0 || watchers.size > 0;
    function ensure() {
      if (!ws && !retry) connect();
    }
    // Each page waits a random moment, so many open pages do not fetch
    // after the same signal at the same instant.
    function signal(set) {
      setTimeout(() => emit(set), Math.random() * 1000);
    }
    function idle() {
      if (needed() || !ws) return;
      const s = ws;
      ws = null;
      s.close(1000);
      clearInterval(beat);
      setStatus("closed");
    }
    function connect() {
      retry = null;
      if (!needed() || stopped) return;
      setStatus("connecting");
      const s = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/__ics/realtime");
      ws = s;
      s.onmessage = (ev) => {
        heard = Date.now();
        let m;
        try {
          m = JSON.parse(ev.data);
        } catch {
          return;
        }
        if (m.t === "hello") {
          attempt = 0;
          for (const name of rooms.keys()) send({ t: "sub", ch: name });
          for (const c of watchers.keys()) send({ t: "watch", c });
          setStatus("open");
          // Changes made while the page was away were not heard.
          if (opened) for (const set of watchers.values()) signal(set);
          opened = true;
        } else if (m.t === "msg") {
          const ch = rooms.get(m.ch);
          if (ch) emit(ch._on.message, m.d, m.from);
        } else if (m.t === "presence") {
          const ch = rooms.get(m.ch);
          if (ch) {
            ch.members = m.members;
            emit(ch._on.presence, m.members);
          }
        } else if (m.t === "changed") {
          const set = watchers.get(m.c);
          if (set) signal(set);
        } else if (m.t === "error") {
          emit(events.error, { code: m.code, ref: m.ref });
        }
      };
      s.onclose = (ev) => {
        if (ws !== s) return;
        ws = null;
        clearInterval(beat);
        setStatus("closed");
        if (ev.code === 4403) {
          stopped = true;
          emit(events.error, { code: "access_lost" });
          return;
        }
        if (!needed()) return;
        // A broker going away (1001) closes many pages at once: they come
        // back spread over several seconds.
        const delay = ev.code === 1001 && attempt === 0 ? 1000 + Math.random() * 9000 : Math.min(30000, 500 * 2 ** attempt) * (0.5 + Math.random() / 2);
        attempt = Math.min(attempt + 1, 10);
        retry = setTimeout(connect, delay);
      };
      s.onopen = () => {
        heard = Date.now();
        clearInterval(beat);
        // A connection that died without a close (sleep, network change)
        // is noticed here instead of waiting for the operating system.
        beat = setInterval(() => {
          if (Date.now() - heard > 70000) s.close();
          else send({ t: "ping" });
        }, 25000);
      };
    }
    function channel(name) {
      let ch = rooms.get(name);
      if (ch) return ch;
      const on = { message: new Set(), presence: new Set() };
      ch = {
        name,
        members: [],
        _on: on,
        send: (data) => rooms.get(name) === ch && send({ t: "pub", ch: name, d: data }),
        on(kind, fn) {
          on[kind].add(fn);
          return () => on[kind].delete(fn);
        },
        leave() {
          if (rooms.get(name) !== ch) return;
          rooms.delete(name);
          send({ t: "unsub", ch: name });
          idle();
        },
      };
      rooms.set(name, ch);
      send({ t: "sub", ch: name });
      ensure();
      return ch;
    }
    function watch(name, callback) {
      let set = watchers.get(name);
      if (!set) {
        watchers.set(name, (set = new Set()));
        send({ t: "watch", c: name });
      }
      // A wrapper, so the same callback can be watched twice and unwatched once.
      const entry = () => callback();
      set.add(entry);
      ensure();
      return () => {
        if (!set.delete(entry) || set.size || watchers.get(name) !== set) return;
        watchers.delete(name);
        send({ t: "unwatch", c: name });
        idle();
      };
    }
    return {
      watch,
      api: Object.freeze({
        channel,
        on(kind, fn) {
          events[kind].add(fn);
          return () => events[kind].delete(fn);
        },
        get status() {
          return status;
        },
      }),
    };
  })();
  function collection(name) {
    const base = "/api/v1/collections/" + encodeURIComponent(name);
    return {
      watch: (callback) => realtime.watch(name, callback),
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
  window.ics = Object.freeze({ session, collection, call, newKey, IcsApiError, realtime: realtime.api });
})();
`;
