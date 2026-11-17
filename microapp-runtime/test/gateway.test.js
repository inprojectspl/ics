// Share-link entry of the gateway: who keeps which session, and the budgets.
import { test } from "node:test";
import assert from "node:assert/strict";
import { Gateway } from "../src/broker/gateway.js";
import { RateLimiter } from "../src/broker/ratelimit.js";
import { SESSION_COOKIE, START_COOKIE, issueSession, readSession } from "../src/broker/session.js";

const SECRET = "test-secret";
const HEX = "a".repeat(32);
const target = { host: "k7m2q9x4.apps.test", assetHex: HEX, environment: "prod" };
const TOKEN = "T".repeat(43);

function gateway(ics = {}) {
  return new Gateway({ config: { sessionSecret: SECRET, icsPublicBaseUrl: "https://ics.test" }, ics, apps: null, pools: null, runners: null });
}

function fakeRes() {
  return { status: 0, headers: {}, body: "", writeHead(s, h) { this.status = s; this.headers = h; }, end(b) { this.body = b ?? ""; } };
}

const sessionOf = (opts) => issueSession(SECRET, { ...target, ...opts });

test("a share link starts the ICS launch for a visitor without a session", () => {
  const res = fakeRes();
  gateway().startShare(res, target, new URL(`https://${target.host}/__ics/share?token=${TOKEN}`), null);
  assert.equal(res.status, 302);
  assert.ok(res.headers.location.startsWith(`https://ics.test/api/share/${TOKEN}/launch?host=`));
  assert.ok(String(res.headers["set-cookie"]).startsWith(`${START_COOKIE}=`));
});

test("a share link keeps a signed-in member's own session", () => {
  const res = fakeRes();
  const own = sessionOf({ userId: "u1" }).payload;
  gateway().startShare(res, target, new URL(`https://${target.host}/__ics/share?token=${TOKEN}`), own);
  assert.equal(res.headers.location, "/");
  assert.equal(res.headers["set-cookie"], undefined);
});

test("the callback keeps the visitor identity of the same link only", async () => {
  const ics = { exchangeLaunch: async () => ({ asset_hex: HEX, environment: "prod", user_id: null, share_id: "s1" }) };
  const call = async (prior) => {
    const res = fakeRes();
    const cookie = [`${START_COOKIE}=n.${Buffer.from("/").toString("base64url")}`, prior ? `${SESSION_COOKIE}=${prior}` : ""].join("; ");
    await gateway(ics).callback({ headers: { cookie } }, res, target, new URL(`https://${target.host}/__ics/callback?code=c`));
    const value = res.headers["set-cookie"][0].split(";")[0].split("=").slice(1).join("=");
    return readSession(SECRET, value, target);
  };
  const same = sessionOf({ userId: "visitor-1", shareId: "s1" }).value;
  assert.equal((await call(same)).uid, "visitor-1");
  const other = sessionOf({ userId: "visitor-2", shareId: "s2" }).value;
  const fresh = await call(other);
  assert.notEqual(fresh.uid, "visitor-2");
  assert.equal(fresh.sh, "s1");
});

test("a link has one budget however many visitor identities it mints", async () => {
  const g = gateway();
  g.config.rateLimits = { userPerSecond: 5, linkPerSecond: 1 };
  // Link burst is twice the refill: two visitors pass, a third identity waits.
  await g.rateLimit(target, { uid: "v1", sh: "s1" });
  await g.rateLimit(target, { uid: "v2", sh: "s1" });
  await assert.rejects(g.rateLimit(target, { uid: "v3", sh: "s1" }), (e) => e.status === 429);
});

test("a refused request spends nothing from the other buckets", async () => {
  const limiter = new RateLimiter();
  const user = { key: "u", burst: 2, perSecond: 0.001 };
  const link = { key: "l", burst: 1, perSecond: 0.001 };
  assert.equal(await limiter.take([user, link]), true);
  assert.equal(await limiter.take([user, link]), false);
  // The user bucket still holds its second token.
  assert.equal(await limiter.take([user]), true);
});

test("the local table stays bounded and drops only the least recently used", async () => {
  const limiter = new RateLimiter();
  const one = (key) => [{ key, burst: 1, perSecond: 0.001 }];
  for (let i = 0; i < 20000; i++) await limiter.take(one(`junk-${i}`));
  assert.ok(limiter.local.size <= 10000);
  // A key still in use keeps its empty bucket instead of starting full.
  assert.equal(await limiter.take(one("junk-19999")), false);
});

test("a full data quota refuses inserts and updates before touching the database", async () => {
  const data = await import("../src/broker/data.js");
  const ctx = { dataFull: true };
  await assert.rejects(data.insert(null, ctx, null, null, {}), (e) => e.status === 507 && e.code === "app_data_quota_exceeded");
  await assert.rejects(data.update(null, ctx, null, null, "x", {}, 1), (e) => e.code === "app_data_quota_exceeded");
});

test("the session tells the page which app roles the person holds", () => {
  const res = fakeRes();
  const auth = { asset_id: "a1", title: "T", release: { id: "r1" }, data_generation: 1, roles: ["reviewer"],
                 user: { id: "u1", display_name: "Carol", email: "c@x" } };
  gateway().sessionInfo({ res, auth, session: { sid: "s", h: target.host }, target, requestId: "q", permissions: new Set(["requests.approve"]) });
  const body = JSON.parse(res.body);
  assert.deepEqual(body.roles, ["reviewer"]);
  assert.deepEqual(body.permissions, ["requests.approve"]);
});
