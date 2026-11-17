// Short app hosts: the mapping comes from ICS, and a host never carries a
// session, a launch code or a CSRF token over to another origin.
import { test } from "node:test";
import assert from "node:assert/strict";
import { Gateway } from "../src/broker/gateway.js";
import { HostResolver } from "../src/broker/hosts.js";
import { START_COOKIE, checkCsrf, csrfToken, issueSession, readSession } from "../src/broker/session.js";

const SECRET = "test-secret";
const HEX = "a".repeat(32);
const OTHER_HEX = "b".repeat(32);
const SUFFIX = "apps.test";
const SHORT = `k7m2q9x4.${SUFFIX}`;
const LEGACY = `a-${HEX}-prod.${SUFFIX}`;
const config = { hostSuffix: SUFFIX, sessionSecret: SECRET, icsPublicBaseUrl: "https://ics.test", aliases: new Map([["demo.tunnel.test", HEX]]) };

function fakeIcs(map = { [SHORT]: HEX }) {
  const calls = [];
  return {
    calls,
    async resolveHost(host) {
      calls.push(host);
      if (!map[host]) throw Object.assign(new Error("unknown application"), { status: 404, code: "not_found" });
      return { host, asset_hex: map[host], environment: "prod" };
    },
  };
}

function fakeRes() {
  return { status: 0, headers: {}, body: "", writeHead(s, h) { this.status = s; this.headers = h ?? {}; }, end(b) { this.body = b ?? ""; } };
}

test("a short host maps to its app through ICS, once", async () => {
  const ics = fakeIcs();
  const hosts = new HostResolver({ config, ics });
  assert.deepEqual(await hosts.resolve("K7M2Q9X4.apps.test"), { host: SHORT, assetHex: HEX, environment: "prod" });
  assert.deepEqual(await hosts.resolve(SHORT), { host: SHORT, assetHex: HEX, environment: "prod" });
  assert.deepEqual(ics.calls, [SHORT]);
});

test("long hosts and aliases keep naming their app without asking ICS", async () => {
  const ics = fakeIcs();
  const hosts = new HostResolver({ config, ics });
  assert.deepEqual(await hosts.resolve(LEGACY), { host: LEGACY, assetHex: HEX, environment: "prod" });
  assert.equal((await hosts.resolve("demo.tunnel.test")).assetHex, HEX);
  assert.deepEqual(ics.calls, []);
});

test("malformed hosts are refused before ICS is asked", async () => {
  const ics = fakeIcs();
  const hosts = new HostResolver({ config, ics });
  for (const host of [
    "k7m2q9x.apps.test", // 7 characters
    "k7m2q9x4a.apps.test", // 9 characters
    "k0m2q9x4.apps.test", // 0 is not in the alphabet
    "k7m2q9l4.apps.test", // nor is l
    "x.k7m2q9x4.apps.test", // a deeper label
    "k7m2q9x4.apps.test.evil.test", // another domain
    "k7m2q9x4.evilapps.test",
    `a-${HEX}-dev.${SUFFIX}`,
    "",
    undefined,
  ]) {
    assert.equal(await hosts.resolve(host), null, String(host));
  }
  assert.deepEqual(ics.calls, []);
});

test("an unknown short host is refused and the miss is remembered briefly", async () => {
  let now = 1_000;
  const ics = fakeIcs();
  const hosts = new HostResolver({ config, ics, now: () => now });
  const host = `zzzzzzzz.${SUFFIX}`;
  assert.equal(await hosts.resolve(host), null);
  assert.equal(await hosts.resolve(host), null);
  assert.equal(ics.calls.length, 1);
  now += 11_000;
  assert.equal(await hosts.resolve(host), null);
  assert.equal(ics.calls.length, 2);
});

test("parallel requests of a new host ask ICS once", async () => {
  const ics = fakeIcs();
  const hosts = new HostResolver({ config, ics });
  const all = await Promise.all([1, 2, 3].map(() => hosts.resolve(SHORT)));
  assert.ok(all.every((t) => t.assetHex === HEX));
  assert.deepEqual(ics.calls, [SHORT]);
});

test("an ICS answer for another host or with a bad id is not trusted", async () => {
  for (const answer of [{ host: `other123.${SUFFIX}`, asset_hex: HEX, environment: "prod" }, { host: SHORT, asset_hex: "x", environment: "prod" }, { host: SHORT, asset_hex: HEX, environment: "dev" }]) {
    const hosts = new HostResolver({ config, ics: { resolveHost: async () => answer } });
    assert.equal(await hosts.resolve(SHORT), null);
  }
});

test("ICS being down is an outage, not an unknown app", async () => {
  const ics = { resolveHost: async () => { throw Object.assign(new Error("ICS unreachable"), { status: 503, code: "ics_unavailable" }); } };
  const g = new Gateway({ config, ics, apps: null, pools: null, runners: null });
  const res = fakeRes();
  await g.handle({ headers: { host: SHORT }, url: "/" }, res);
  assert.equal(res.status, 503);
  assert.equal(JSON.parse(res.body).code, "ics_unavailable");
});

test("the gateway answers 404 for an unknown host and starts sign-in on a known one", async () => {
  const g = new Gateway({ config, ics: fakeIcs(), apps: null, pools: null, runners: null });
  const unknown = fakeRes();
  await g.handle({ headers: { host: `zzzzzzzz.${SUFFIX}` }, url: "/" }, unknown);
  assert.equal(unknown.status, 404);
  const known = fakeRes();
  await g.handle({ headers: { host: SHORT }, url: "/" }, known);
  assert.equal(known.status, 302);
  const launch = new URL(known.headers.location);
  assert.equal(launch.origin + launch.pathname, "https://ics.test/api/micro-applications/launch");
  assert.equal(launch.searchParams.get("host"), SHORT);
});

test("a session is valid only on the host and app it was issued for", () => {
  const short = { host: SHORT, assetHex: HEX, environment: "prod" };
  const legacy = { host: LEGACY, assetHex: HEX, environment: "prod" };
  const onLegacy = issueSession(SECRET, { userId: "u1", ...legacy });
  assert.equal(readSession(SECRET, onLegacy.value, legacy).uid, "u1");
  // Same app, new host: the old session does not move over.
  assert.equal(readSession(SECRET, onLegacy.value, short), null);
  // Same host text, another app behind it.
  assert.equal(readSession(SECRET, issueSession(SECRET, { userId: "u1", ...short }).value, { ...short, assetHex: OTHER_HEX }), null);
  // A CSRF token of the old host's session does not pass for a new one.
  const onShort = issueSession(SECRET, { userId: "u1", ...short }).payload;
  assert.equal(checkCsrf(SECRET, onShort, csrfToken(SECRET, onLegacy.payload)), false);
});

test("a launch code for another app or host is refused at the callback", async () => {
  const target = { host: SHORT, assetHex: HEX, environment: "prod" };
  const cookie = `${START_COOKIE}=n.${Buffer.from("/").toString("base64url")}`;
  const exchanged = [];
  const ics = {
    async exchangeLaunch(code, host) {
      exchanged.push(host);
      if (host !== SHORT) throw Object.assign(new Error("the launch code belongs to another start"), { status: 400, code: "launch_invalid" });
      return { asset_hex: OTHER_HEX, environment: "prod", user_id: "u1", share_id: null };
    },
  };
  const g = new Gateway({ config, ics, apps: null, pools: null, runners: null });
  await assert.rejects(g.callback({ headers: { cookie } }, fakeRes(), target, new URL(`https://${SHORT}/__ics/callback?code=c`)), (e) => e.code === "launch_invalid");
  await assert.rejects(g.callback({ headers: { cookie } }, fakeRes(), { ...target, host: LEGACY }, new URL(`https://${LEGACY}/__ics/callback?code=c`)), (e) => e.code === "launch_invalid");
  assert.deepEqual(exchanged, [SHORT, LEGACY]);
});

test("writes need the exact Origin of the host the session belongs to", () => {
  const g = new Gateway({ config, ics: fakeIcs(), apps: null, pools: null, runners: null });
  const target = { host: SHORT, assetHex: HEX, environment: "prod" };
  const session = issueSession(SECRET, { userId: "u1", ...target }).payload;
  const token = csrfToken(SECRET, session);
  const write = (origin, csrf = token) => () => g.checkWrite({ headers: { origin, "x-ics-csrf": csrf } }, target, session);
  assert.doesNotThrow(write(`https://${SHORT}`));
  assert.throws(write(`https://${LEGACY}`), (e) => e.code === "csrf_failed");
  assert.throws(write(`https://other123.${SUFFIX}`), (e) => e.code === "csrf_failed");
  assert.throws(write(`https://${SHORT}`, "forged"), (e) => e.code === "csrf_failed");
});
