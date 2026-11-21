// Copyable app addresses: the URL rules (gateway and the shared script),
// head injection and the gateway's entry page.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { Gateway } from "../src/broker/gateway.js";
import { SESSION_COOKIE, issueSession } from "../src/broker/session.js";
import { ShareContextScript, cleanTarget, headInsertAt, injectHead, isDocumentPath, readToken, targetPath, withToken } from "../src/broker/share-context.js";

const T = "A".repeat(43);
const B = "B".repeat(43);

// The script the gateway serves, as ICS keeps it; outside a browser it only
// exposes its URL rules.
const SCRIPT = new URL("../../backend/app/static/share_context.js", import.meta.url);
const sandbox = { URL };
vm.runInNewContext(readFileSync(SCRIPT, "utf8"), sandbox);
const core = sandbox.IcsShareContextCore;

test("both readers agree on the token of a query", () => {
  const cases = [
    ["", "none"],
    ["tab=2", "none"],
    [`ics_share=${T}`, "one"],
    [`?lang=pl&ics_share=${T}&x=1`, "one"],
    [`ics%5Fshare=${T}`, "one"],
    [`ics_share=${T}&ics_share=${T}`, "invalid"],
    [`ics_share=${T}&ics_share=${B}`, "invalid"],
    ["ics_share=short", "invalid"],
    ["ics_share", "invalid"],
  ];
  for (const [query, state] of cases) {
    assert.equal(readToken(query).state, state, query);
    assert.equal(core.readToken(query).state, state, query);
  }
  assert.equal(core.readToken(`?ics_share=${T}`).token, T);
});

test("the token goes before the fragment, once, and nothing else changes", () => {
  assert.equal(withToken("tab=2&a=%20b&a=c", T), `tab=2&a=%20b&a=c&ics_share=${T}`);
  const set = core.setToken;
  assert.equal(set("szczegoly.html#koszty", T), `szczegoly.html?ics_share=${T}#koszty`);
  assert.equal(set("?tab=2#koszty", T), `?tab=2&ics_share=${T}#koszty`);
  assert.equal(set(`/r.html?ics_share=${B}&x=1`, T), `/r.html?x=1&ics_share=${T}`);
  // The hash router's own query is part of the fragment and stays put.
  assert.equal(set("/#/ustawienia?tab=2", T), `/?ics_share=${T}#/ustawienia?tab=2`);
  assert.equal(set(`/a?x=1&ics_share=${T}#f`, null), "/a?x=1#f");
  assert.equal(set("/a?x=%2F&y", null), "/a?x=%2F&y");
});

test("only pages of the same asset are decorated", () => {
  const env = { origin: "https://app.example.net", scope: "/", kind: "micro_application", base: "https://app.example.net/raport", here: `https://app.example.net/raport?ics_share=${T}` };
  const dec = (raw) => core.decorate(raw, T, env);
  assert.equal(dec("board"), `board?ics_share=${T}`);
  assert.equal(dec("/settings?tab=2#konto"), `/settings?tab=2&ics_share=${T}#konto`);
  assert.equal(dec("page.html"), `page.html?ics_share=${T}`);
  // Local anchors, other links of the author, other origins, files and APIs stay.
  for (const raw of ["#koszty", `?ics_share=${B}`, "https://other.example/x", "mailto:a@b.c", "javascript:void(0)", "/api/v1/session", "/__ics/sdk.js", "app.js", "logo.png", "data:text/html,x"]) {
    assert.equal(dec(raw), raw, raw);
  }
  assert.equal(core.decorate("board", null, env), "board");

  // HTML bundles share one host: the asset's own prefix is the boundary.
  const bundle = { origin: "https://html.example.net", scope: "/raport/", kind: "html_bundle", base: "https://html.example.net/raport/index.html", here: `https://html.example.net/raport/index.html?ics_share=${T}` };
  assert.equal(core.decorate("sub/a.html", T, bundle), `sub/a.html?ics_share=${T}`);
  assert.equal(core.decorate("/other/index.html", T, bundle), "/other/index.html");
  assert.equal(core.decorate("/_/grant?t=x", T, bundle), "/_/grant?t=x");
  assert.equal(core.decorate("sub/", T, bundle), "sub/");
  assert.equal(core.isDocumentPath("/raport/a.HTM", "html_bundle"), true);
  assert.equal(isDocumentPath("/board"), true);
  assert.equal(isDocumentPath("/app.js"), false);
  assert.equal(isDocumentPath("/api/v1/x"), false);
});

test("page targets never leave the app", () => {
  assert.equal(cleanTarget(`board?tab=2&ics_share=${T}`), "board?tab=2");
  assert.equal(cleanTarget("a/b.html"), "a/b.html");
  for (const evil of ["", null, "/x", "//evil.example/", "%2F%2Fevil", "../x", "a/%2e%2e/b", "a/%252e%252e/b", "a//b", "a\\b", "a%5Cb", "x\n", "x#f", "__ics/callback", "API/v1/session", "%5F_ics/share", "x".repeat(2049)]) {
    assert.equal(cleanTarget(evil), null, String(evil));
  }
  assert.equal(targetPath("board?tab=2", T), `/board?tab=2&ics_share=${T}`);
  assert.equal(targetPath("", T), `/?ics_share=${T}`);
});

test("the bootstrap goes into the head before the page's own code", () => {
  const snip = "<script data-x></script>";
  const cases = [
    ['<!doctype html><html><head><meta charset="utf-8"><title>x</title>', "<title>"],
    ["<!DOCTYPE html><head><title>a</title><script src=app.js></script>", "<script src"],
    ["<!-- <head><script> --><html><head><script>x</script>", "<script>x"],
    ["<!doctype html><script>early()</script><p>x</p>", "<script>early"],
    ["<html><head></head><body>", "</head>"],
    ['<head><meta name="a>b" content=x><script>1</script>', "<script>1"],
    ["<head><title>a <script> b</title><script>2</script>", "<script>2"],
  ];
  for (const [raw, marker] of cases) {
    const out = injectHead(Buffer.from(raw), snip).toString();
    assert.equal(out.split(snip).length, 2, raw);
    assert.equal(out.indexOf(snip) + snip.length, out.indexOf(marker), raw);
  }
  const bom = Buffer.concat([Buffer.from([0xef, 0xbb, 0xbf]), Buffer.from("<script>1</script>")]);
  assert.equal(headInsertAt(bom), 3);
  assert.equal(headInsertAt(Buffer.from("<!-- open <script>")), 0);
});

// ---------- through the gateway ----------

const HEX = "a".repeat(32);
const target = { host: "k7m2q9x4.apps.test", assetHex: HEX, environment: "prod" };
const SECRET = "test-secret";
const PAGE = '<!doctype html><html><head><meta charset="utf-8"><title>App</title><script src="app.js"></script></head><body>Secret</body></html>';

function fakeRes() {
  return { status: 0, headers: {}, body: "", writeHead(s, h) { this.status = s; this.headers = h; }, end(b) { this.body = b === undefined ? "" : String(b); } };
}

function gatewayWith({ shareTokenId = null, shareContext = true, calls = [] } = {}) {
  const ics = {
    authorize: async (...args) => {
      calls.push(args);
      return { found: true, app_use: true, user: { id: "u" }, desired_state: "enabled", release: { id: "r1" }, permissions: [], share_context: shareContext, share_token_id: shareTokenId };
    },
    publicFile: async (_rid, path) => ({ bytes: Buffer.from(path.endsWith(".html") ? PAGE : "js()") }),
    shareContextScript: async () => ({ body: Buffer.from("/*script*/"), etag: '"e1"' }),
  };
  const apps = {
    get: () => ({ key: "k" }),
    sync: async () => {},
    model: async () => ({ bundle: { manifest: { frontend: { entry: "public/index.html" } }, public_files: ["public/index.html", "public/app.js"] }, model: {} }),
  };
  return new Gateway({ config: { sessionSecret: SECRET, icsPublicBaseUrl: "https://ics.test" }, ics, apps, pools: null, runners: null, hosts: { resolve: async () => target } });
}

async function get(g, url, { session, cookie = "" } = {}) {
  const res = fakeRes();
  const jar = [cookie, session ? `${SESSION_COOKIE}=${issueSession(SECRET, { ...target, ...session }).value}` : ""].filter(Boolean).join("; ");
  await g.handle({ method: "GET", url, headers: { host: target.host, cookie: jar } }, res);
  return res;
}

test("without a session a page gets the entry page, files and data the old answers", async () => {
  const g = gatewayWith();
  const page = await get(g, `/board?x=1&ics_share=${T}`);
  assert.equal(page.status, 401);
  assert.ok(page.body.includes('data-entry-mode="recover"') && !page.body.includes("Secret"));
  assert.ok(page.body.includes('data-recover-share="/__ics/share?token={token}&amp;to={to}"'));
  assert.ok(page.body.includes(`url=/__ics/login?to=${encodeURIComponent("board?x=1")}`));
  assert.equal(page.headers["cache-control"], "no-store");
  assert.equal((await get(g, "/app.js")).status, 302);
  assert.equal((await get(g, "/api/v1/session")).status, 401);
  const login = await get(g, "/__ics/login?to=board%3Fx%3D1");
  assert.equal(login.status, 302);
  assert.ok(login.headers.location.startsWith("https://ics.test/api/micro-applications/launch?"));
});

test("a page carries the bootstrap; a member's own launch is marked direct once", async () => {
  const calls = [];
  const g = gatewayWith({ shareTokenId: "s1", calls });
  const res = await get(g, `/?ics_share=${T}`, { session: { userId: "u1", shareId: "s1" }, cookie: "__Host-ics-app-entry=launch-123456" });
  assert.equal(res.status, 200);
  assert.equal(calls[0][4], T);
  const tag = res.body.indexOf('<script src="/__ics/share-context.js"');
  assert.ok(res.body.indexOf("<meta charset") < tag && tag < res.body.indexOf("<title>"));
  assert.ok(res.body.includes('data-entry-mode="direct"') && res.body.includes('data-launch="launch-123456"'));
  assert.match(res.headers["set-cookie"], /^__Host-ics-app-entry=; .*Max-Age=0/);
  assert.equal(Number(res.headers["content-length"]), Buffer.byteLength(res.body));

  const js = await get(g, "/app.js", { session: { userId: "u1", shareId: "s1" } });
  assert.equal(js.body, "js()");
  assert.equal(calls.at(-1)[4], null);

  const off = await get(gatewayWith({ shareContext: false }), "/", { session: { userId: "u1" } });
  assert.ok(off.body === PAGE);
});

test("the link in the address must be the visitor's own, a member keeps theirs", async () => {
  // Guest of link s1 opening an address of link s2: a new entry through s2.
  const crossed = await get(gatewayWith({ shareTokenId: "s2" }), `/?ics_share=${B}`, { session: { userId: "v", shareId: "s1" } });
  assert.equal(crossed.status, 401);
  assert.ok(crossed.body.includes('data-entry-mode="recover"'));
  // A dead or foreign link: the entry page sends the browser to ICS, which explains.
  const dead = await get(gatewayWith({ shareTokenId: null }), `/?ics_share=${B}`, { session: { userId: "u1" } });
  assert.equal(dead.status, 401);
  // A member with a live link of this app keeps their own session.
  const member = await get(gatewayWith({ shareTokenId: "s2" }), `/?ics_share=${B}`, { session: { userId: "u1" } });
  assert.equal(member.status, 200);
  const twice = await get(gatewayWith({ shareTokenId: "s1" }), `/?ics_share=${T}&ics_share=${T}`, { session: { userId: "v", shareId: "s1" } });
  assert.equal(twice.status, 400);
});

test("the script comes from ICS once and survives a short ICS outage", async () => {
  let n = 0;
  let down = false;
  const cache = new ShareContextScript({ shareContextScript: async () => {
    n++;
    if (down) throw new Error("ICS down");
    return { body: Buffer.from(`v${n}`), etag: null };
  } }, 0);
  assert.equal(String((await cache.get()).body), "v1");
  down = true;
  assert.equal(String((await cache.get()).body), "v1");
  const g = gatewayWith();
  const res = await get(g, "/__ics/share-context.js");
  assert.equal(res.status, 200);
  assert.equal(res.headers["content-type"], "text/javascript; charset=utf-8");
  assert.equal(res.body, "/*script*/");
  const again = fakeRes();
  await g.handle({ method: "GET", url: "/__ics/share-context.js", headers: { host: target.host, "if-none-match": '"e1"' } }, again);
  assert.equal(again.status, 304);
});
