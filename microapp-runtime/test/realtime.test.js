// Realtime sockets of app pages (ADR-0032): sign-in, permissions, rooms,
// presence, change signals after commit only, limits and the report.
import { test } from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import WebSocket from "ws";
import * as data from "../src/broker/data.js";
import { AppRegistry } from "../src/broker/apps.js";
import { Gateway } from "../src/broker/gateway.js";
import { parseChannels } from "../src/broker/model.js";
import { createClient } from "redis";
import { RateLimiter } from "../src/broker/ratelimit.js";
import { Realtime, RedisBus } from "../src/broker/realtime.js";
import { SESSION_COOKIE, issueSession } from "../src/broker/session.js";

const SECRET = "s".repeat(32);
const HEX = "c".repeat(32);
const HOST = "k7m2q9x4.apps.test";
const ORIGIN = `https://${HOST}`;
const APP_KEY = `${HEX}:prod`;
const ALL = ["n.read", "n.write", "chat.use"];

const manifest = {
  database: {
    collections: {
      notes: {
        fields: { text: { type: "string", maxLength: 100 } },
        crud: { list: { permission: "n.read", rowScope: "all" }, create: { permission: "n.write", rowScope: "all", writeFields: ["text"] } },
      },
      secrets: { fields: { text: { type: "string", maxLength: 100 } }, crud: { list: { permission: "s.read", rowScope: "all" } } },
    },
  },
  permissions: { "n.read": {}, "n.write": {}, "s.read": {}, "chat.use": {}, admin: {} },
  realtime: {
    channels: {
      board: { permission: "chat.use", presence: true },
      small: { permission: "chat.use", maxMessageBytes: 100 },
      slow: { permission: "chat.use", messagesPerSecond: 1 },
      admin: { permission: "admin" },
    },
  },
  capabilities: {},
  endpoints: [],
};

/** Pub/sub and presence hashes shared by several in-process brokers. */
function memoryBus(shared = { subs: new Map(), hashes: new Map() }) {
  const mine = new Map();
  return {
    shared,
    ready: true,
    async publish(channel, message) {
      const listeners = shared.subs.get(channel) ?? new Set();
      for (const l of listeners) setImmediate(() => l(message, channel));
      return listeners.size;
    },
    async subscribe(channel, listener) {
      mine.set(channel, listener);
      if (!shared.subs.has(channel)) shared.subs.set(channel, new Set());
      shared.subs.get(channel).add(listener);
    },
    async unsubscribe(channel) {
      shared.subs.get(channel)?.delete(mine.get(channel));
      mine.delete(channel);
    },
    async presence(key, set, del) {
      const h = shared.hashes.get(key) ?? new Map();
      for (const [f, v] of set) h.set(f, v);
      for (const f of del) h.delete(f);
      shared.hashes.set(key, h);
      return Object.fromEntries(h);
    },
    async dropFields(key, fields) {
      for (const f of fields) shared.hashes.get(key)?.delete(f);
    },
    async close() {},
  };
}

async function broker(t, { limits = {}, bus = null, serverOptions = {} } = {}) {
  const access = new Map(); // uid -> false when revoked
  const perms = new Map(); // uid -> permissions
  const control = { desired_state: "enabled" };
  const ics = {
    async authorize(hex, env, uid) {
      const ok = access.get(uid) !== false;
      return {
        found: true,
        deleted: false,
        app_use: ok,
        user: ok ? { id: uid, display_name: `User ${uid}` } : null,
        asset_id: "asset-1",
        desired_state: control.desired_state,
        release: { id: "r1" },
        permissions: perms.get(uid) ?? ALL,
        control_generation: 1,
        credential_generation: 1,
        data_generation: 1,
      };
    },
    bundle: async () => ({ manifest, schema: "a_x" }),
  };
  const apps = new AppRegistry({ ics, pools: { stats: () => ({ open: 0 }), closeApp() {} }, runners: { queuedFor: () => 0, recycleAsset: async () => {} }, idleSeconds: 600 });
  const hosts = { resolve: async (h) => (h === HOST ? { host: HOST, assetHex: HEX, environment: "prod" } : null) };
  const gateway = new Gateway({ config: { sessionSecret: SECRET, rateLimits: { userPerSecond: 1000 } }, ics, apps, pools: null, runners: null, hosts });
  const rt = new Realtime({ gateway, limits: { presenceMs: 30, ...limits }, bus });
  apps.realtime = rt;
  const server = http.createServer(serverOptions, (req, res) => {
    res.writeHead(404);
    res.end();
  });
  rt.attach(server);
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const env = { rt, apps, gateway, access, perms, control, port: server.address().port, clients: [] };
  t.after(async () => {
    for (const c of env.clients) c.ws.terminate();
    await rt.shutdown();
    await new Promise((resolve) => server.close(resolve));
  });
  return env;
}

function socket(env, uid, { origin = ORIGIN, cookie = true, path = "/__ics/realtime", host = HOST } = {}) {
  const headers = { host, origin };
  if (cookie) headers.cookie = `${SESSION_COOKIE}=${issueSession(SECRET, { userId: uid, assetHex: HEX, environment: "prod", host: HOST }).value}`;
  const ws = new WebSocket(`ws://127.0.0.1:${env.port}${path}`, { headers });
  const inbox = [];
  const waiters = new Set();
  ws.on("message", (raw) => {
    const m = JSON.parse(raw);
    for (const w of waiters) {
      if (w.pred(m)) {
        waiters.delete(w);
        return w.resolve(m);
      }
    }
    inbox.push(m);
  });
  ws.on("error", () => {});
  const c = {
    ws,
    inbox,
    closed: new Promise((resolve) => ws.on("close", (code) => resolve(code))),
    refused: new Promise((resolve) => ws.on("unexpected-response", (req, res) => resolve(res.statusCode))),
    next(pred = () => true, ms = 2000) {
      const i = inbox.findIndex(pred);
      if (i >= 0) return Promise.resolve(inbox.splice(i, 1)[0]);
      return new Promise((resolve, reject) => {
        const w = { pred, resolve };
        waiters.add(w);
        setTimeout(() => waiters.delete(w) && reject(new Error("no matching frame")), ms).unref();
      });
    },
    send(msg) {
      ws.send(typeof msg === "string" ? msg : JSON.stringify(msg));
    },
    // Frames to this socket are in order: after the pong nothing earlier is pending.
    async settle() {
      c.send({ t: "ping" });
      await c.next((m) => m.t === "pong");
    },
  };
  env.clients.push(c);
  return c;
}

async function open(env, uid, opts) {
  const c = socket(env, uid, opts);
  c.hello = await c.next((m) => m.t === "hello");
  return c;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const kinds = (c, t) => c.inbox.filter((m) => m.t === t);

test("a socket needs the app session, the app's own origin and its path", async (t) => {
  const env = await broker(t);
  assert.equal(await socket(env, "u1", { cookie: false }).refused, 401);
  assert.equal(await socket(env, "u1", { origin: "https://other.apps.test" }).refused, 403);
  assert.equal(await socket(env, "u1", { origin: `http://${HOST}` }).refused, 403);
  assert.equal(await socket(env, "u1", { path: "/__ics/other" }).refused, 404);
  assert.equal(await socket(env, "u1", { host: "unknown.test" }).refused, 404);
  env.access.set("u9", false);
  assert.equal(await socket(env, "u9").refused, 403);
  const c = await open(env, "u1");
  assert.deepEqual(c.hello.user, { id: "u1", name: "User u1" });
  assert.equal(c.hello.limits.maxSubscriptions, 50);
});

test("an upgraded socket outlives the HTTP request timeouts", async (t) => {
  const env = await broker(t, { serverOptions: { requestTimeout: 300, headersTimeout: 200, connectionsCheckingInterval: 50 } });
  const c = await open(env, "u1");
  await sleep(700);
  await c.settle();
});

test("watching needs the collection's list permission", async (t) => {
  const env = await broker(t);
  const c = await open(env, "u1");
  c.send({ t: "watch", c: "secrets" });
  assert.deepEqual(await c.next((m) => m.t === "error"), { t: "error", code: "forbidden", ref: "secrets" });
  c.send({ t: "watch", c: "nothing" });
  assert.deepEqual(await c.next((m) => m.t === "error"), { t: "error", code: "collection_unknown", ref: "nothing" });
  c.send({ t: "watch", c: "notes" });
  await c.settle();
  env.apps.markChanged(env.apps.get(HEX, "prod"), ["notes", "secrets"]);
  assert.deepEqual(await c.next((m) => m.t === "changed"), { t: "changed", c: "notes" });
  await sleep(50);
  await c.settle();
  assert.equal(kinds(c, "changed").length, 0, "no signal for a collection it may not list");
});

test("change signals are coalesced per collection", async (t) => {
  const env = await broker(t, { limits: { changedMs: 150 } });
  const c = await open(env, "u1");
  c.send({ t: "watch", c: "notes" });
  await c.settle();
  const app = env.apps.get(HEX, "prod");
  for (let i = 0; i < 10; i += 1) env.apps.markChanged(app, ["notes"]);
  await c.next((m) => m.t === "changed");
  await sleep(400);
  await c.settle();
  // The first at once, one more for the rest, then quiet.
  assert.equal(kinds(c, "changed").length, 1);
  c.send({ t: "unwatch", c: "notes" });
  await c.settle();
  c.inbox.length = 0;
  env.apps.markChanged(app, ["notes"]);
  await sleep(50);
  await c.settle();
  assert.equal(kinds(c, "changed").length, 0);
});

function fakeClient({ failCommit = false } = {}) {
  return {
    async query(text) {
      if (text === "COMMIT" && failCommit) throw new Error("connection lost");
      if (text.startsWith("INSERT INTO \"a_x\".\"notes\"")) return { rows: [{ id: "id1", revision: 1 }], rowCount: 1 };
      return { rows: [], rowCount: 0 };
    },
    release() {},
  };
}

test("a write marks its collection changed after the commit, never after a rollback", async (t) => {
  const env = await broker(t, { limits: { changedMs: 20 } });
  const c = await open(env, "u1");
  c.send({ t: "watch", c: "notes" });
  await c.settle();
  const app = env.apps.get(HEX, "prod");
  const { model } = await env.apps.model("r1");
  const collection = model.collection("notes");
  const rule = data.crudRule(collection, "create");
  const write = async ({ fail = false, failCommit = false } = {}) => {
    env.gateway.pools = { connect: async () => fakeClient({ failCommit }) };
    const ctx = { schema: "a_x", actorId: "u1", requestId: "req", releaseId: "r1", dataGeneration: 1 };
    const run = async (client, cx) => {
      await data.insert(client, cx, collection, rule, { text: "x" });
      if (fail) throw new Error("handler failed after the insert");
      return { status: 201 };
    };
    return env.gateway.transact({ app, requestId: "req" }, { schema: "a_x" }, ctx, { routeKey: "r", key: null, requestHash: "h", run });
  };

  await assert.rejects(write({ fail: true }));
  await sleep(60);
  await c.settle();
  assert.equal(kinds(c, "changed").length, 0);
  assert.equal(app.changed.size, 0);

  await write();
  await c.next((m) => m.t === "changed" && m.c === "notes");
  assert.deepEqual([...app.changed], ["notes"]);

  // An unknown commit outcome may have committed: it is announced too.
  app.changed.clear();
  await sleep(60);
  await assert.rejects(write({ failCommit: true }), (e) => e.code === "commit_unknown");
  await c.next((m) => m.t === "changed" && m.c === "notes");
});

test("channels need their permission and a valid room", async (t) => {
  const env = await broker(t);
  env.perms.set("u2", ["n.read"]);
  const c = await open(env, "u2");
  c.send({ t: "sub", ch: "board/r1" });
  assert.deepEqual(await c.next((m) => m.t === "error"), { t: "error", code: "forbidden", ref: "board/r1" });
  const a = await open(env, "u1");
  for (const [ch, code] of [["admin", "forbidden"], ["nope", "channel_unknown"], ["board/a b", "bad_message"], ["board/x/y", "bad_message"], [`board/${"k".repeat(65)}`, "bad_message"]]) {
    a.send({ t: "sub", ch });
    assert.equal((await a.next((m) => m.t === "error")).code, code, ch);
  }
  a.send({ t: "pub", ch: "board/r1", d: 1 });
  assert.equal((await a.next((m) => m.t === "error")).code, "not_subscribed");
  a.send("not json");
  assert.equal((await a.next((m) => m.t === "error")).code, "bad_message");
});

test("a message reaches the other subscribers of the room, not the sender", async (t) => {
  const env = await broker(t);
  const [a, b, c] = [await open(env, "u1"), await open(env, "u2"), await open(env, "u3")];
  a.send({ t: "sub", ch: "small/r1" });
  b.send({ t: "sub", ch: "small/r1" });
  c.send({ t: "sub", ch: "small/r2" });
  await Promise.all([a.settle(), b.settle(), c.settle()]);
  a.send({ t: "pub", ch: "small/r1", d: { move: "e4" } });
  assert.deepEqual(await b.next((m) => m.t === "msg"), { t: "msg", ch: "small/r1", from: { id: "u1", name: "User u1" }, d: { move: "e4" } });
  await Promise.all([a.settle(), c.settle()]);
  assert.equal(kinds(a, "msg").length + kinds(c, "msg").length, 0);
});

test("presence lists the room's people with their sockets", async (t) => {
  const env = await broker(t);
  const a = await open(env, "u1");
  const b = await open(env, "u2");
  a.send({ t: "sub", ch: "board/r1" });
  b.send({ t: "sub", ch: "board/r1" });
  const both = (m) => m.t === "presence" && m.members.length === 2;
  assert.deepEqual((await a.next(both)).members, [{ id: "u1", name: "User u1", n: 1 }, { id: "u2", name: "User u2", n: 1 }]);
  await b.next(both);
  const a2 = await open(env, "u1");
  a2.send({ t: "sub", ch: "board/r1" });
  const two = await a2.next((m) => m.t === "presence");
  assert.deepEqual(two.members[0], { id: "u1", name: "User u1", n: 2 });
  await a.settle();
  a.inbox.length = 0;
  b.ws.close();
  await a.next((m) => m.t === "presence" && m.members.length === 1);
});

test("size limits: per channel on the data, the platform cap on the frame", async (t) => {
  const env = await broker(t, { limits: { maxMessageBytes: 2048 } });
  const a = await open(env, "u1");
  a.send({ t: "sub", ch: "small" });
  a.send({ t: "pub", ch: "small", d: "x".repeat(90) });
  a.send({ t: "pub", ch: "small", d: "x".repeat(200) });
  assert.deepEqual(await a.next((m) => m.t === "error"), { t: "error", code: "message_too_large", ref: "small" });
  a.send({ t: "pub", ch: "small", d: "x".repeat(4000) });
  assert.equal(await a.closed, 1009);
});

test("rate limits per socket and per channel", async (t) => {
  const env = await broker(t, { limits: { messagesPerSecond: 3 } });
  const a = await open(env, "u1");
  for (let i = 0; i < 10; i += 1) a.send({ t: "ping" });
  assert.deepEqual(await a.next((m) => m.t === "error"), { t: "error", code: "rate_limited" });
  const env2 = await broker(t);
  const b = await open(env2, "u1");
  b.send({ t: "sub", ch: "slow" });
  for (let i = 0; i < 3; i += 1) b.send({ t: "pub", ch: "slow", d: i });
  assert.deepEqual(await b.next((m) => m.t === "error"), { t: "error", code: "rate_limited", ref: "slow" });
});

test("socket and subscription counts are limited", async (t) => {
  const env = await broker(t, { limits: { maxSocketsPerPerson: 1, maxSubscriptions: 2 } });
  const a = await open(env, "u1");
  assert.equal(await socket(env, "u1").refused, 429);
  a.send({ t: "sub", ch: "board" });
  a.send({ t: "watch", c: "notes" });
  a.send({ t: "sub", ch: "small" });
  assert.deepEqual(await a.next((m) => m.t === "error"), { t: "error", code: "too_many_subscriptions", ref: "small" });
});

test("a page that does not read is closed (4008)", async (t) => {
  const env = await broker(t);
  const a = await open(env, "u1");
  const b = await open(env, "u2");
  a.send({ t: "sub", ch: "small" });
  b.send({ t: "sub", ch: "small" });
  await Promise.all([a.settle(), b.settle()]);
  const slow = [...env.rt.hubs.get(APP_KEY).conns].find((c) => c.user.id === "u2");
  Object.defineProperty(slow.ws, "bufferedAmount", { get: () => 2 * 1024 * 1024 });
  a.send({ t: "pub", ch: "small", d: 1 });
  assert.equal(await b.closed, 4008);
  assert.deepEqual(env.rt.stats(APP_KEY), { sockets: 1, people: 1 });
});

test("losing access closes with 4403; a lost permission ends the subscription", async (t) => {
  const env = await broker(t);
  const a = await open(env, "u1");
  const b = await open(env, "u2");
  b.send({ t: "sub", ch: "small/r" });
  b.send({ t: "watch", c: "notes" });
  await b.settle();
  env.access.set("u1", false);
  env.perms.set("u2", ["s.read"]);
  await env.rt.reauthorize();
  assert.equal(await a.closed, 4403);
  const errors = [await b.next((m) => m.t === "error"), await b.next((m) => m.t === "error")];
  assert.deepEqual(errors.map((e) => e.ref).sort(), ["notes", "small/r"]);
  assert.equal(env.rt.hubs.get(APP_KEY).rooms.size, 0);
});

test("a suspended app closes its sockets with 1013 and refuses new ones", async (t) => {
  const env = await broker(t);
  const a = await open(env, "u1");
  env.control.desired_state = "suspended";
  await env.rt.reauthorize();
  assert.equal(await a.closed, 1013);
  assert.equal(await socket(env, "u1").refused, 503);
});

test("re-authorization is staggered and a socket that spoke lately is not pinged", async (t) => {
  const env = await broker(t, { limits: { pingMs: 1000, authMs: 60_000 } });
  const before = Date.now();
  await open(env, "u1");
  const conn = [...env.rt.hubs.get(APP_KEY).conns][0];
  assert.ok(conn.authAt <= before + 50 && conn.authAt > before - 60_000);
  let pings = 0;
  conn.ws.ping = () => {
    pings += 1;
  };
  conn.lastPing = 0;
  conn.lastSeen = Date.now();
  await env.rt.sweep();
  assert.equal(pings, 0);
  conn.lastPing = 0;
  conn.lastSeen = Date.now() - 2000;
  await env.rt.sweep();
  assert.equal(pings, 1);
});

test("the report counts sockets and people and lists changed collections", async (t) => {
  const env = await broker(t);
  await open(env, "u1");
  await open(env, "u1");
  await open(env, "u2");
  const app = env.apps.get(HEX, "prod");
  env.apps.markChanged(app, ["notes"]);
  // An app without open pages still reports its changes.
  const other = env.apps.get("d".repeat(32), "prod");
  other.assetId = "asset-2";
  env.apps.markChanged(other, ["items"]);
  const row = (snap, id) => snap.find((a) => a.asset_id === id);
  const drained = env.apps.drainChanged();
  const snap = env.apps.snapshot(drained);
  assert.deepEqual(row(snap, "asset-1").realtime, { sockets: 3, people: 2 });
  assert.deepEqual(row(snap, "asset-1").changed_collections, ["notes"]);
  assert.deepEqual(row(snap, "asset-2").realtime, { sockets: 0, people: 0 });
  assert.deepEqual(row(snap, "asset-2").changed_collections, ["items"]);
  assert.deepEqual(row(env.apps.snapshot(env.apps.drainChanged()), "asset-1").changed_collections, []);
  // A failed report hands its changes to the next one.
  env.apps.markChanged(app, ["other"]);
  env.apps.restoreChanged(drained);
  assert.deepEqual(row(env.apps.snapshot(env.apps.drainChanged()), "asset-1").changed_collections, ["notes", "other"]);
});

async function acrossBrokers(t, makeBus, subscribers) {
  const one = await broker(t, { bus: makeBus(), limits: { changedMs: 20 } });
  const two = await broker(t, { bus: makeBus(), limits: { changedMs: 20 } });
  // Subscriptions are asynchronous on a real Redis.
  const settled = async (n) => {
    for (let i = 0; i < 50 && (await subscribers()) !== n; i += 1) await sleep(20);
    assert.equal(await subscribers(), n);
  };
  const a = await open(one, "u1");
  const a2 = await open(one, "u3");
  const b = await open(two, "u2");
  for (const c of [a, a2, b]) c.send({ t: "sub", ch: "board/r1" });
  b.send({ t: "watch", c: "notes" });
  await Promise.all([a.settle(), a2.settle(), b.settle()]);
  await settled(2);
  a.send({ t: "pub", ch: "board/r1", d: "hi" });
  assert.equal((await b.next((m) => m.t === "msg")).d, "hi");
  assert.equal((await a2.next((m) => m.t === "msg")).d, "hi");
  await sleep(30);
  await a2.settle();
  assert.equal(kinds(a2, "msg").length, 0, "delivered once on the sender's broker");
  const all3 = (m) => m.t === "presence" && m.members.length === 3;
  await b.next(all3, 3000);
  await a.next(all3, 3000);
  one.apps.markChanged(one.apps.get(HEX, "prod"), ["notes"]);
  await b.next((m) => m.t === "changed");
  // The last socket of the app on a broker ends its subscription.
  await a.settle();
  a.inbox.length = 0;
  b.ws.close();
  await b.closed;
  await settled(1);
  await a.next((m) => m.t === "presence" && m.members.length === 2, 3000);
}

test("brokers share rooms, presence and change signals through the bus", async (t) => {
  const shared = { subs: new Map(), hashes: new Map() };
  await acrossBrokers(t, () => memoryBus(shared), () => shared.subs.get(`ics:rt:${HEX}`)?.size ?? 0);
});

test("a broker alone on an app publishes nothing until another one joins", async (t) => {
  const shared = { subs: new Map(), hashes: new Map() };
  const sent = [];
  const counting = () => {
    const bus = memoryBus(shared);
    const publish = bus.publish;
    bus.publish = (channel, message) => {
      sent.push(message.split("\t")[0]);
      return publish(channel, message);
    };
    return bus;
  };
  const one = await broker(t, { bus: counting(), limits: { changedMs: 20 } });
  const a = await open(one, "u1");
  const a2 = await open(one, "u3");
  for (const c of [a, a2]) c.send({ t: "sub", ch: "board/r1" });
  a2.send({ t: "watch", c: "notes" });
  await a.next((m) => m.t === "presence" && m.members.length === 2);
  a.send({ t: "pub", ch: "board/r1", d: 1 });
  await a2.next((m) => m.t === "msg");
  one.apps.markChanged(one.apps.get(HEX, "prod"), ["notes"]);
  await a2.next((m) => m.t === "changed");
  assert.deepEqual(sent, ["j"], "only the join, answered by this broker alone");
  assert.equal(shared.hashes.size, 0, "presence stays in memory");
  // A second broker joins: the first writes its presence and publishes again.
  const two = await broker(t, { bus: counting(), limits: { changedMs: 20 } });
  const b = await open(two, "u2");
  b.send({ t: "sub", ch: "board/r1" });
  await b.next((m) => m.t === "presence" && m.members.length === 3, 3000);
  a.send({ t: "pub", ch: "board/r1", d: 2 });
  assert.equal((await b.next((m) => m.t === "msg")).d, 2);
});

test("presence writes only the fields that changed", async (t) => {
  const shared = { subs: new Map(), hashes: new Map() };
  const writes = [];
  const bus = memoryBus(shared);
  const presence = bus.presence;
  bus.presence = (key, set, del, ttl) => {
    writes.push(set.map(([f]) => f.split("|")[1]));
    return presence(key, set, del, ttl);
  };
  const env = await broker(t, { bus });
  // Another subscriber of the app's channel: this broker is not alone.
  shared.subs.set(`ics:rt:${HEX}`, new Set([() => {}]));
  const a = await open(env, "u1");
  a.send({ t: "sub", ch: "board/r1" });
  await a.next((m) => m.t === "presence" && m.members.length === 1);
  const b = await open(env, "u2");
  b.send({ t: "sub", ch: "board/r1" });
  await a.next((m) => m.t === "presence" && m.members.length === 2);
  assert.deepEqual(writes, [["u1"], ["u2"]]);
});

// ICS_TEST_REDIS_URL=redis://127.0.0.1:6379/15 npm test
test("brokers share rooms, presence and change signals through Redis", { skip: !process.env.ICS_TEST_REDIS_URL }, async (t) => {
  const probe = createClient({ url: process.env.ICS_TEST_REDIS_URL });
  await probe.connect();
  t.after(() => probe.quit());
  // As in the broker: the rate limiter's client publishes, a duplicate subscribes.
  const makeBus = () => {
    const limiter = new RateLimiter({ redisUrl: process.env.ICS_TEST_REDIS_URL });
    const bus = new RedisBus(limiter.redis);
    const close = bus.close.bind(bus);
    bus.close = async () => {
      await close();
      await limiter.close();
    };
    return bus;
  };
  await acrossBrokers(t, makeBus, async () => Number((await probe.pubSubNumSub(`ics:rt:${HEX}`))[`ics:rt:${HEX}`] ?? 0));
});

test("shutdown closes sockets with 1001", async (t) => {
  const env = await broker(t);
  const a = await open(env, "u1");
  await env.rt.shutdown();
  assert.equal(await a.closed, 1001);
  assert.equal(await socket(env, "u1").refused, 503);
});

test("manifest channels: defaults, and names safe for Redis keys", () => {
  const m = (channels) => ({ permissions: { p: {} }, realtime: { channels } });
  assert.equal(parseChannels({ permissions: {} }).size, 0);
  const ch = parseChannels(m({ chat: { permission: "p" }, big: { permission: "p", maxMessageBytes: 131072, presence: true, messagesPerSecond: 5 } }));
  assert.deepEqual(ch.get("chat"), { name: "chat", permission: "p", presence: false, maxMessageBytes: 65536, messagesPerSecond: null });
  assert.deepEqual(ch.get("big"), { name: "big", permission: "p", presence: true, maxMessageBytes: 131072, messagesPerSecond: 5 });
  // ICS validated the rest at publication.
  for (const bad of [{ Chat: { permission: "p" } }, { "a/b": { permission: "p" } }, { "a:b": { permission: "p" } }]) {
    assert.throws(() => parseChannels(m(bad)), /realtime channel/, JSON.stringify(bad));
  }
});
