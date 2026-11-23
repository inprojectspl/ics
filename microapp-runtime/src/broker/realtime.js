// Realtime connections of app pages (ADR-0032): one WebSocket per open page
// at wss://<app origin>/__ics/realtime. A socket hears that a collection it
// may list changed (the name only, never records) and carries the app's own
// messages between pages in the rooms of its declared channels. Nothing is
// stored; an open socket never wakes the app's runners.
//
// Several brokers share the work through Redis: one pub/sub channel per app
// (`ics:rt:<asset hex>`), subscribed while this broker holds sockets of the
// app, and one hash per presence room with a heartbeat. A broker alone on an
// app's channel (PUBLISH reached only itself) stops publishing and keeps
// presence in memory until another broker joins. Without Redis the hub
// works in-process (one broker, tests).
import crypto from "node:crypto";
import { STATUS_CODES } from "node:http";
import { WebSocketServer } from "ws";
import * as data from "./data.js";
import { HttpError } from "./http.js";
import { IDENT_RE } from "./model.js";
import { SESSION_COOKIE, parseCookies, readSession } from "./session.js";

const RT_PATH = "/__ics/realtime";
const BUS_PREFIX = "ics:rt:";
const PRESENCE_PREFIX = "ics:rtp:";
const ROOM_KEY_RE = /^[A-Za-z0-9_-]{1,64}$/;
// ICS calls of the periodic re-authorization at a time.
const AUTH_CONCURRENCY = 32;

const CLOSE = { goingAway: 1001, tryLater: 1013, tooSlow: 4008, accessLost: 4403 };

const DEFAULT_LIMITS = {
  maxMessageBytes: 131072, // whole frame, platform cap
  messagesPerSecond: 30, // per socket, burst twice that
  maxSocketsPerApp: 2000,
  maxSocketsPerPerson: 20,
  maxSubscriptions: 50, // channels and watched collections together
  maxBufferedBytes: 1024 * 1024, // unsent data per socket
  pingMs: 30_000,
  silenceMs: 75_000,
  authMs: 60_000,
  // ICS unreachable this long: sockets close and reconnect later.
  authGraceMs: 180_000,
  changedMs: 1000,
  presenceMs: 500,
  presenceBeatMs: 20_000,
  presenceTtlMs: 60_000,
};

/** Limits from the broker environment (unset or invalid: the default). */
export function limitsFromEnv(env) {
  const int = (name, fallback) => {
    const n = Number(env[name]);
    return Number.isSafeInteger(n) && n > 0 ? n : fallback;
  };
  return {
    maxMessageBytes: int("ICS_MICROAPPS_RT_MAX_MESSAGE_BYTES", DEFAULT_LIMITS.maxMessageBytes),
    messagesPerSecond: int("ICS_MICROAPPS_RT_MESSAGES_PER_SECOND", DEFAULT_LIMITS.messagesPerSecond),
    maxSocketsPerApp: int("ICS_MICROAPPS_RT_MAX_SOCKETS_PER_APP", DEFAULT_LIMITS.maxSocketsPerApp),
    maxSocketsPerPerson: int("ICS_MICROAPPS_RT_MAX_SOCKETS_PER_PERSON", DEFAULT_LIMITS.maxSocketsPerPerson),
    maxSubscriptions: int("ICS_MICROAPPS_RT_MAX_SUBSCRIPTIONS", DEFAULT_LIMITS.maxSubscriptions),
  };
}

/** Pub/sub and presence storage in Redis: `client` (the rate limiter's,
 * owned by its creator) publishes and stores; a duplicate of it is the
 * subscriber (a subscribed connection takes no other commands). */
export class RedisBus {
  constructor(client) {
    this.pub = client;
    // The subscriber queues while reconnecting and node-redis subscribes
    // again after a reconnect, so a short Redis outage needs no bookkeeping.
    this.sub = client.duplicate({ disableOfflineQueue: false });
    this.sub.on("error", () => {});
    this.sub.connect().catch(() => {});
  }

  get ready() {
    return this.pub.isReady;
  }

  /** Resolves to the number of subscribers that received it. */
  publish(channel, message) {
    return this.pub.publish(channel, message);
  }

  subscribe(channel, listener) {
    return this.sub.subscribe(channel, listener);
  }

  unsubscribe(channel) {
    return this.sub.unsubscribe(channel);
  }

  /** Write this broker's fields of a presence hash, drop the gone ones and
   * read the whole hash back, in one round trip. */
  async presence(key, set, del, ttlMs) {
    const m = this.pub.multi();
    if (set.length) m.hSet(key, Object.fromEntries(set));
    if (del.length) m.hDel(key, del);
    if (set.length) m.pExpire(key, ttlMs);
    m.hGetAll(key);
    const replies = await m.exec();
    return replies[replies.length - 1] ?? {};
  }

  dropFields(key, fields) {
    return this.pub.hDel(key, fields);
  }

  async close() {
    if (this.sub.isOpen) await this.sub.quit().catch(() => {});
  }
}

function reject(socket, status, code) {
  if (socket.destroyed) return;
  const body = JSON.stringify({ code });
  socket.end(`HTTP/1.1 ${status} ${STATUS_CODES[status] ?? ""}\r\nConnection: close\r\nContent-Type: application/json\r\nCache-Control: no-store\r\nContent-Length: ${Buffer.byteLength(body)}\r\n\r\n${body}`);
}

/** A token bucket of one socket (or one socket's room): `perSecond`, burst twice that. */
function take(bucket, perSecond, now) {
  bucket.tokens = Math.min(perSecond * 2, bucket.tokens + ((now - bucket.at) / 1000) * perSecond);
  bucket.at = now;
  if (bucket.tokens < 1) return false;
  bucket.tokens -= 1;
  return true;
}

export class Realtime {
  /**
   * `gateway`: host resolution, ICS client, app registry and request budget
   * of the app origins; `bus`: a RedisBus (or the same interface), null for
   * a single broker.
   */
  constructor({ gateway, incarnation = crypto.randomUUID(), limits = {}, bus = null, now = Date.now }) {
    this.gw = gateway;
    this.apps = gateway.apps;
    this.incarnation = incarnation;
    this.limits = { ...DEFAULT_LIMITS, ...limits };
    this.bus = bus;
    this.now = now;
    this.closing = false;
    this.hubs = new Map(); // app key -> per-app state, only while it has sockets or pending work
    this.origin = new Map(); // throttle of published change signals, "<app key>|<collection>"
    // The cap is enforced by ws on the whole frame before it is buffered.
    this.wss = new WebSocketServer({ noServer: true, maxPayload: this.limits.maxMessageBytes, perMessageDeflate: false, clientTracking: false });
    this.onBus = (message, channel) => this.#fromBus(message, channel);
    this.timer = setInterval(() => this.sweep().catch(() => {}), Math.min(this.limits.pingMs, 15_000));
    this.timer.unref();
    this.beat = setInterval(() => this.#presenceBeat(), this.limits.presenceBeatMs);
    this.beat.unref();
  }

  attach(server) {
    server.on("upgrade", (req, socket, head) => {
      socket.on("error", () => {});
      this.upgrade(req, socket, head).catch(() => reject(socket, 500, "internal_error"));
    });
  }

  // ---------- opening ----------

  async upgrade(req, socket, head) {
    if (this.closing) return reject(socket, 503, "shutting_down");
    const target = await this.gw.hosts.resolve(req.headers.host);
    if (!target) return reject(socket, 404, "not_found");
    let url;
    try {
      url = new URL(req.url, `https://${target.host}`);
    } catch {
      return reject(socket, 400, "bad_request");
    }
    if (url.pathname !== RT_PATH) return reject(socket, 404, "not_found");
    if (req.method !== "GET" || String(req.headers.upgrade).toLowerCase() !== "websocket") return reject(socket, 400, "bad_request");
    // Browsers send the app cookie on cross-site WebSocket opens too: only
    // the app's own origin may use it (an alias is its own origin).
    if (req.headers.origin !== `https://${target.host}`) return reject(socket, 403, "origin_refused");
    const session = readSession(this.gw.config.sessionSecret, parseCookies(req.headers.cookie)[SESSION_COOKIE], target);
    if (!session) return reject(socket, 401, "app_session_required");
    try {
      await this.gw.rateLimit(target, session);
    } catch (err) {
      return reject(socket, err.status ?? 429, err.code ?? "rate_limited");
    }
    let admitted;
    try {
      admitted = await this.gw.admit(target, session);
    } catch (err) {
      if (err instanceof HttpError) return reject(socket, err.status, err.code);
      throw err;
    }
    const { auth, app, model } = admitted;
    const known = this.hubs.get(app.key);
    if ((known?.conns.size ?? 0) >= this.limits.maxSocketsPerApp) return reject(socket, 429, "too_many_sockets");
    if ((known?.people.get(auth.user.id) ?? 0) >= this.limits.maxSocketsPerPerson) return reject(socket, 429, "too_many_sockets");
    if (socket.destroyed || this.closing) return;
    // ws completes the handshake synchronously, so the counts checked above
    // cannot be overtaken by another opening socket.
    this.wss.handleUpgrade(req, socket, head, (ws) => this.#open(ws, this.#hub(app), { session, auth, model }));
  }

  #hub(app) {
    let hub = this.hubs.get(app.key);
    if (!hub) {
      hub = {
        key: app.key,
        app,
        bus: `${BUS_PREFIX}${app.assetHex}`,
        conns: new Set(),
        people: new Map(), // person id -> sockets
        rooms: new Map(), // room -> Set(conn)
        watchers: new Map(), // collection -> Set(conn)
        throttle: new Map(), // delivery throttle of change signals from other brokers
        presence: new Map(), // room -> {timer, publish, renew, last, fresh}
        written: new Map(), // room -> Map(field -> members' state) this broker wrote to the presence hash
        subscribed: false,
        // Subscribed and announced: a PUBLISH reply now counts this broker.
        listening: false,
        // Other brokers may hold sockets of the app; unknown counts as yes.
        peers: true,
        // Bumped when a broker joins, so an older PUBLISH reply cannot undo it.
        epoch: 0,
      };
      this.hubs.set(app.key, hub);
    }
    return hub;
  }

  #open(ws, hub, { session, auth, model }) {
    const now = this.now();
    const conn = {
      id: crypto.randomBytes(9).toString("base64url"),
      ws,
      hub,
      session,
      user: { id: auth.user.id, name: auth.user.display_name ?? "" },
      permissions: new Set(auth.permissions),
      model,
      subs: new Map(), // room -> {channel, bucket}
      watches: new Set(),
      bucket: { tokens: this.limits.messagesPerSecond * 2, at: now },
      lastSeen: now,
      lastPing: now,
      // Staggered, so sockets opened together (a broker restart) are not
      // authorized again together.
      authAt: now - Math.random() * this.limits.authMs,
      authOkAt: now,
      lastRateError: 0,
      closed: false,
    };
    hub.conns.add(conn);
    hub.people.set(conn.user.id, (hub.people.get(conn.user.id) ?? 0) + 1);
    if (!hub.subscribed && this.bus) {
      hub.subscribed = true;
      hub.listening = false;
      hub.peers = true;
      this.bus
        .subscribe(hub.bus, this.onBus)
        .then(() => {
          if (!hub.subscribed) return;
          hub.listening = true;
          // Tells the brokers already there to publish again; its reply
          // tells whether there are any.
          this.#publish(hub, hub.bus, `j\t${this.incarnation}\t${hub.app.environment}\t1`);
        })
        .catch(() => {});
    }
    ws.on("message", (raw, isBinary) => this.#message(conn, raw, isBinary));
    ws.on("pong", () => {
      conn.lastSeen = this.now();
    });
    ws.on("close", () => this.#detach(conn));
    ws.on("error", () => {});
    const limits = { maxMessageBytes: this.limits.maxMessageBytes, messagesPerSecond: this.limits.messagesPerSecond, maxSubscriptions: this.limits.maxSubscriptions };
    this.#send(conn, JSON.stringify({ t: "hello", conn: conn.id, user: conn.user, limits }));
  }

  // ---------- frames from a page ----------

  #error(conn, code, ref) {
    this.#send(conn, JSON.stringify(ref === undefined ? { t: "error", code } : { t: "error", code, ref }));
  }

  #message(conn, raw, isBinary) {
    if (conn.closed) return;
    const now = this.now();
    conn.lastSeen = now;
    if (!take(conn.bucket, this.limits.messagesPerSecond, now)) {
      // One answer a second is enough for a page that floods.
      if (now - conn.lastRateError >= 1000) {
        conn.lastRateError = now;
        this.#error(conn, "rate_limited");
      }
      return;
    }
    let msg;
    try {
      msg = isBinary ? null : JSON.parse(raw.toString("utf8"));
    } catch {
      msg = null;
    }
    if (!msg || typeof msg !== "object" || typeof msg.t !== "string") return this.#error(conn, "bad_message");
    switch (msg.t) {
      case "ping":
        return this.#send(conn, '{"t":"pong"}');
      case "watch":
        return this.#watch(conn, msg.c);
      case "unwatch":
        return this.#unwatch(conn, msg.c);
      case "sub":
        return this.#sub(conn, msg.ch);
      case "unsub":
        return this.#unsub(conn, msg.ch);
      case "pub":
        return this.#pub(conn, msg, raw.length, now);
      default:
        return this.#error(conn, "bad_message");
    }
  }

  /** The collection's list rule decides who hears about it. */
  #mayWatch(conn, name) {
    const collection = conn.model.collections.get(name);
    if (!collection) return "collection_unknown";
    const rule = data.crudRule(collection, "list");
    return rule && conn.permissions.has(rule.permission) ? null : "forbidden";
  }

  #watch(conn, name) {
    if (typeof name !== "string" || !IDENT_RE.test(name)) return this.#error(conn, "bad_message");
    if (conn.watches.has(name)) return;
    const why = this.#mayWatch(conn, name);
    if (why) return this.#error(conn, why, name);
    if (conn.watches.size + conn.subs.size >= this.limits.maxSubscriptions) return this.#error(conn, "too_many_subscriptions", name);
    conn.watches.add(name);
    let set = conn.hub.watchers.get(name);
    if (!set) conn.hub.watchers.set(name, (set = new Set()));
    set.add(conn);
  }

  #unwatch(conn, name) {
    if (typeof name !== "string" || !conn.watches.delete(name)) return;
    const set = conn.hub.watchers.get(name);
    set?.delete(conn);
    if (set && !set.size) conn.hub.watchers.delete(name);
  }

  /** `<channel>` or `<channel>/<key>`: [room, channel] or an error code. */
  #channelOf(conn, room) {
    if (typeof room !== "string" || room.length > 113) return [null, "bad_message"];
    const slash = room.indexOf("/");
    const name = slash < 0 ? room : room.slice(0, slash);
    if (!IDENT_RE.test(name) || (slash >= 0 && !ROOM_KEY_RE.test(room.slice(slash + 1)))) return [null, "bad_message"];
    const channel = conn.model.channels.get(name);
    if (!channel) return [null, "channel_unknown"];
    if (!conn.permissions.has(channel.permission)) return [null, "forbidden"];
    return [channel, null];
  }

  #sub(conn, room) {
    if (conn.subs.has(room)) return;
    const [channel, why] = this.#channelOf(conn, room);
    if (why) return this.#error(conn, why, typeof room === "string" ? room.slice(0, 113) : undefined);
    if (conn.watches.size + conn.subs.size >= this.limits.maxSubscriptions) return this.#error(conn, "too_many_subscriptions", room);
    conn.subs.set(room, { channel, bucket: { tokens: (channel.messagesPerSecond ?? 0) * 2, at: this.now() } });
    const hub = conn.hub;
    let set = hub.rooms.get(room);
    if (!set) hub.rooms.set(room, (set = new Set()));
    set.add(conn);
    if (channel.presence) this.#presenceSoon(hub, room, true, conn);
  }

  #unsub(conn, room) {
    const sub = typeof room === "string" ? conn.subs.get(room) : undefined;
    if (!sub) return;
    conn.subs.delete(room);
    const set = conn.hub.rooms.get(room);
    set?.delete(conn);
    if (set && !set.size) conn.hub.rooms.delete(room);
    if (sub.channel.presence) this.#presenceSoon(conn.hub, room, true);
  }

  #pub(conn, msg, size, now) {
    const sub = typeof msg.ch === "string" ? conn.subs.get(msg.ch) : undefined;
    if (!sub) return this.#error(conn, "not_subscribed", typeof msg.ch === "string" ? msg.ch.slice(0, 113) : undefined);
    if (msg.d === undefined) return this.#error(conn, "bad_message", msg.ch);
    // The limit is on the JSON of `d`; the frame is a cheap upper bound of it.
    if (size > sub.channel.maxMessageBytes && Buffer.byteLength(JSON.stringify(msg.d)) > sub.channel.maxMessageBytes) {
      return this.#error(conn, "message_too_large", msg.ch);
    }
    const rate = sub.channel.messagesPerSecond;
    if (rate && rate < this.limits.messagesPerSecond && !take(sub.bucket, rate, now)) return this.#error(conn, "rate_limited", msg.ch);
    // Serialized once here; other brokers forward the same text unparsed.
    const frame = JSON.stringify({ t: "msg", ch: msg.ch, from: conn.user, d: msg.d });
    this.#toRoom(conn.hub, msg.ch, frame, conn);
    this.#publish(conn.hub, conn.hub.bus, `m\t${this.incarnation}\t${conn.hub.app.environment}\t${msg.ch}\n${frame}`);
  }

  #toRoom(hub, room, frame, except = null) {
    const set = hub.rooms.get(room);
    if (set) this.#sendAll(set, frame, except);
  }

  // ---------- sending and closing ----------

  /** `frame`: a string or its UTF-8 bytes, sent as a text frame. */
  #send(conn, frame) {
    if (conn.closed) return;
    // A page that does not read must not make the broker hold its data.
    if (conn.ws.bufferedAmount > this.limits.maxBufferedBytes) return this.#kill(conn, CLOSE.tooSlow, "too slow");
    conn.ws.send(frame, { binary: false });
  }

  /** Encoded once for every recipient. */
  #sendAll(conns, frame, except = null) {
    const bytes = Buffer.from(frame);
    for (const c of conns) if (c !== except) this.#send(c, bytes);
  }

  #kill(conn, code, reason) {
    if (conn.closed) return;
    this.#detach(conn);
    conn.ws.close(code, reason);
    // The close frame may wait behind unsent data; do not wait for it long.
    setTimeout(() => conn.ws.terminate(), 2000).unref();
  }

  #detach(conn) {
    if (conn.closed) return;
    conn.closed = true;
    const hub = conn.hub;
    for (const room of [...conn.subs.keys()]) this.#unsub(conn, room);
    for (const name of [...conn.watches]) this.#unwatch(conn, name);
    hub.conns.delete(conn);
    const n = (hub.people.get(conn.user.id) ?? 1) - 1;
    if (n > 0) hub.people.set(conn.user.id, n);
    else hub.people.delete(conn.user.id);
    if (!hub.conns.size) {
      if (hub.subscribed && this.bus) this.bus.unsubscribe(hub.bus).catch(() => {});
      hub.subscribed = false;
      hub.listening = false;
      this.#maybeDrop(hub);
    }
  }

  // A hub stays while a presence flush is pending, so that flush (not a new
  // hub of the same app) removes this broker's members from Redis.
  #maybeDrop(hub) {
    if (!hub.conns.size && !hub.presence.size && !hub.written.size && this.hubs.get(hub.key) === hub) this.hubs.delete(hub.key);
  }

  // ---------- change signals ----------

  /** After a commit of the app's `names` collections (AppRegistry.markChanged). */
  changed(app, names) {
    for (const name of names) {
      throttle(this.origin, `${app.key}|${name}`, this.limits.changedMs, () => {
        const hub = this.hubs.get(app.key);
        if (hub) this.#sendChanged(hub, name);
        // Without a hub here nothing tells whether other brokers listen.
        this.#publish(hub ?? null, `${BUS_PREFIX}${app.assetHex}`, `c\t${this.incarnation}\t${app.environment}\t${name}`);
      });
    }
  }

  /** A signal from another broker: several may send the same change. */
  #deliverChanged(hub, name) {
    if (hub.watchers.has(name)) throttle(hub.throttle, name, this.limits.changedMs, () => this.#sendChanged(hub, name));
  }

  #sendChanged(hub, name) {
    const set = hub.watchers.get(name);
    if (set) this.#sendAll(set, `{"t":"changed","c":${JSON.stringify(name)}}`);
  }

  #publish(hub, channel, message) {
    if (!this.bus?.ready || hub?.peers === false) return;
    const epoch = hub?.epoch;
    this.bus.publish(channel, message).then(
      (receivers) => {
        // Only this broker heard it: stop publishing until another one joins.
        if (hub?.listening && hub.epoch === epoch && receivers <= 1) hub.peers = false;
      },
      () => {},
    );
  }

  /** Another broker holds sockets of the app: publish again, and put this
   * broker's presence (kept in memory meanwhile) into Redis. */
  #peerSeen(hub, joined) {
    if (joined) hub.epoch += 1;
    if (hub.peers) return;
    hub.peers = true;
    for (const room of hub.rooms.keys()) if (this.#isPresenceRoom(hub, room)) this.#presenceSoon(hub, room, true, null, true);
  }

  /** `<kind>\t<incarnation>\t<environment>\t<arg>[\n<frame>]` from any broker. */
  #fromBus(message, channel) {
    const nl = message.indexOf("\n");
    const [kind, incarnation, environment, arg] = (nl < 0 ? message : message.slice(0, nl)).split("\t");
    // Our own messages were delivered locally when they were sent.
    if (incarnation === this.incarnation || !arg) return;
    const hub = this.hubs.get(`${channel.slice(BUS_PREFIX.length)}:${environment}`);
    if (!hub) return;
    this.#peerSeen(hub, kind === "j");
    if (kind === "m" && nl >= 0) this.#toRoom(hub, arg, message.slice(nl + 1));
    else if (kind === "c" && IDENT_RE.test(arg)) this.#deliverChanged(hub, arg);
    else if (kind === "p" && this.#isPresenceRoom(hub, arg)) this.#presenceSoon(hub, arg, false);
  }

  // ---------- presence ----------

  #isPresenceRoom(hub, room) {
    const first = hub.rooms.get(room)?.values().next().value;
    return Boolean(first?.subs.get(room)?.channel.presence);
  }

  #presenceState(hub, room) {
    let p = hub.presence.get(room);
    if (!p) hub.presence.set(room, (p = { timer: null, publish: false, renew: false, last: null, fresh: new Set() }));
    return p;
  }

  /** Flush a room's presence within `presenceMs`; `publish` tells the other
   * brokers to read it again, `fresh` is a socket that needs the list even
   * if nothing changed, `renew` writes all of this broker's fields again. */
  #presenceSoon(hub, room, publish, fresh = null, renew = false) {
    const p = this.#presenceState(hub, room);
    p.publish ||= publish;
    p.renew ||= renew;
    if (fresh) p.fresh.add(fresh);
    if (!p.timer) {
      p.timer = setTimeout(() => this.#flushPresence(hub, room).catch(() => {}), this.limits.presenceMs);
      p.timer.unref();
    }
  }

  #localMembers(hub, room) {
    const members = new Map();
    for (const c of hub.rooms.get(room) ?? []) {
      const m = members.get(c.user.id);
      if (m) m.n += 1;
      else members.set(c.user.id, { id: c.user.id, name: c.user.name, n: 1 });
    }
    return members;
  }

  async #flushPresence(hub, room) {
    const p = hub.presence.get(room);
    if (!p) return;
    const { publish, renew } = p;
    p.timer = null;
    p.publish = false;
    p.renew = false;
    const local = this.#localMembers(hub, room);
    let members = [...local.values()];
    // Alone on the app: nothing in Redis, except what an earlier peer
    // left to clean up.
    if (this.bus?.ready && (hub.peers || hub.written.has(room))) {
      try {
        const peers = hub.peers;
        const all = await this.#syncPresence(hub, room, peers ? local : new Map(), renew);
        if (peers) {
          members = all;
          if (publish) this.#publish(hub, hub.bus, `p\t${this.incarnation}\t${hub.app.environment}\t${room}`);
        }
      } catch {
        // Redis unavailable: this broker's own members until it is back.
      }
    }
    const listeners = hub.rooms.get(room);
    if (!listeners?.size) {
      if (!p.timer) {
        hub.presence.delete(room);
        this.#maybeDrop(hub);
      }
      return;
    }
    members.sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : a.id < b.id ? -1 : 1));
    const frame = JSON.stringify({ t: "presence", ch: room, members });
    const targets = frame === p.last ? [...p.fresh] : listeners;
    p.last = frame;
    p.fresh.clear();
    this.#sendAll([...targets].filter((c) => c.subs.has(room)), frame);
  }

  /** Write this broker's members of the room that changed since the last
   * write (`renew`: all of them, with a new expiry), read every broker's. */
  async #syncPresence(hub, room, local, renew) {
    const key = `${PRESENCE_PREFIX}${hub.app.assetHex}:${hub.app.environment}:${room}`;
    const now = this.now();
    const exp = now + this.limits.presenceTtlMs;
    const before = hub.written.get(room) ?? new Map();
    const mine = new Map();
    const set = [];
    for (const m of local.values()) {
      const field = `${this.incarnation}|${m.id}`;
      const state = `${m.n}|${m.name}`;
      mine.set(field, state);
      if (renew || before.get(field) !== state) set.push([field, JSON.stringify({ name: m.name, n: m.n, exp })]);
    }
    const del = [...before.keys()].filter((f) => !mine.has(f));
    if (mine.size) hub.written.set(room, mine);
    else hub.written.delete(room);
    const all = await this.bus.presence(key, set, del, this.limits.presenceTtlMs);
    const members = new Map();
    const stale = [];
    for (const [field, value] of Object.entries(all)) {
      let v;
      try {
        v = JSON.parse(value);
      } catch {
        v = null;
      }
      // A broker that died stops renewing its fields; they expire here.
      if (!v || !(v.exp > now)) {
        stale.push(field);
        continue;
      }
      const id = field.slice(field.indexOf("|") + 1);
      const m = members.get(id);
      if (m) m.n += v.n;
      else members.set(id, { id, name: String(v.name ?? ""), n: v.n });
    }
    if (stale.length) this.bus.dropFields(key, stale).catch(() => {});
    return [...members.values()];
  }

  #presenceBeat() {
    // Renews this broker's fields and drops members of brokers that died;
    // a broker alone keeps presence in memory and has nothing to renew.
    if (!this.bus?.ready) return;
    for (const hub of this.hubs.values()) {
      if (!hub.peers) continue;
      for (const room of hub.rooms.keys()) if (this.#isPresenceRoom(hub, room)) this.#presenceSoon(hub, room, false, null, true);
    }
  }

  // ---------- heartbeat and authorization ----------

  /** Ping, close silent sockets, authorize again those due. */
  sweep() {
    const now = this.now();
    const due = new Map();
    for (const hub of this.hubs.values()) {
      for (const conn of [...hub.conns]) {
        if (now - conn.lastSeen > this.limits.silenceMs) {
          this.#detach(conn);
          conn.ws.terminate();
          continue;
        }
        if (now - conn.lastPing >= this.limits.pingMs) {
          conn.lastPing = now;
          // A page that spoke lately (its own pings among others) is alive.
          if (now - conn.lastSeen >= this.limits.pingMs) conn.ws.ping();
        }
        if (now - conn.authAt >= this.limits.authMs) collect(due, hub, conn);
      }
    }
    return this.#authorize(due);
  }

  /** Authorize every socket again now (tests, and a policy change). */
  reauthorize() {
    const due = new Map();
    for (const hub of this.hubs.values()) for (const conn of hub.conns) collect(due, hub, conn);
    return this.#authorize(due);
  }

  // One ICS call per person and app, however many pages they have open,
  // and a bounded number of them at a time.
  async #authorize(due) {
    const groups = [...due.values()];
    const now = this.now();
    // Marked at once, so a sweep while these wait does not queue them again.
    for (const { conns } of groups) for (const c of conns) c.authAt = now;
    let next = 0;
    const worker = async () => {
      while (next < groups.length) await this.#authorizeGroup(groups[next++]);
    };
    await Promise.all(Array.from({ length: Math.min(AUTH_CONCURRENCY, groups.length) }, worker));
  }

  async #authorizeGroup({ hub, session, conns }) {
    const now = this.now();
    let admitted;
    try {
      admitted = await this.gw.admit(hub.app, session);
    } catch (err) {
      if (err instanceof HttpError) {
        for (const c of conns) this.#kill(c, err.status === 503 ? CLOSE.tryLater : CLOSE.accessLost, err.code);
      } else {
        for (const c of conns) if (now - c.authOkAt > this.limits.authGraceMs) this.#kill(c, CLOSE.tryLater, "authorization unavailable");
      }
      return;
    }
    for (const c of conns) this.#refresh(c, admitted.auth, admitted.model, now);
  }

  /** New permissions or release: drop what the socket may no longer hold. */
  #refresh(conn, auth, model, now) {
    if (conn.closed) return;
    conn.authOkAt = now;
    conn.permissions = new Set(auth.permissions);
    conn.model = model;
    for (const name of [...conn.watches]) {
      const why = this.#mayWatch(conn, name);
      if (why) {
        this.#unwatch(conn, name);
        this.#error(conn, why, name);
      }
    }
    for (const [room, sub] of [...conn.subs]) {
      const [channel, why] = this.#channelOf(conn, room);
      if (why) {
        this.#unsub(conn, room);
        this.#error(conn, why, room);
      } else if (channel !== sub.channel) {
        sub.channel = channel;
      }
    }
  }

  // ---------- reporting and shutdown ----------

  /** This broker's sockets and distinct people of an app. */
  stats(appKey) {
    const hub = this.hubs.get(appKey);
    return { sockets: hub?.conns.size ?? 0, people: hub?.people.size ?? 0 };
  }

  /** Close every socket (1001) and take this broker's presence out of Redis. */
  async shutdown() {
    this.closing = true;
    clearInterval(this.timer);
    clearInterval(this.beat);
    const flushes = [];
    for (const hub of [...this.hubs.values()]) {
      for (const conn of [...hub.conns]) {
        this.#detach(conn);
        conn.ws.close(CLOSE.goingAway, "server restarting");
      }
      for (const room of [...hub.written.keys()]) {
        const p = this.#presenceState(hub, room);
        clearTimeout(p.timer);
        p.publish = true;
        flushes.push(this.#flushPresence(hub, room).catch(() => {}));
      }
    }
    for (const s of this.origin.values()) clearTimeout(s.timer);
    await Promise.all(flushes);
    await this.bus?.close();
  }
}

function collect(due, hub, conn) {
  if (conn.closed) return;
  const key = `${hub.key}|${conn.session.uid}|${conn.session.sh ?? ""}`;
  let group = due.get(key);
  if (!group) due.set(key, (group = { hub, session: conn.session, conns: [] }));
  group.conns.push(conn);
}

/** Run `fire` at once, then at most once per `ms` while calls keep coming
 * (the last call always fires); the key is forgotten after a quiet period. */
function throttle(map, key, ms, fire) {
  const state = map.get(key);
  if (state) {
    state.dirty = true;
    return;
  }
  const s = { dirty: false, timer: null };
  const arm = () => {
    s.timer = setTimeout(() => {
      if (!s.dirty) return map.delete(key);
      s.dirty = false;
      fire();
      arm();
    }, ms);
    s.timer.unref();
  };
  map.set(key, s);
  fire();
  arm();
}
