// Public HTTP gateway of every micro-application origin
// (https://<name>.<suffix>, see hosts.js). Serves only the release's public/
// files and the app's own data API; it is not a proxy to the ICS API.
import crypto from "node:crypto";
import * as data from "./data.js";
import { DataError } from "./data.js";
import { inTransaction, mapPgError } from "./db.js";
import { SESSION_COOKIE, START_COOKIE, checkCsrf, cookie, csrfToken, issueSession, newStartNonce, parseCookies, readSession, stateOf } from "./session.js";
import { ValidationError, coerceQuery, validate } from "./validate.js";
import { SDK_SOURCE } from "./sdk.js";
import { quoteIdent } from "./model.js";
import { buildOpenApi, publicSchema } from "./describe.js";
import { invokeHandler } from "./custom.js";
import { RateLimiter } from "./ratelimit.js";
import { HostResolver } from "./hosts.js";
import { HttpError, SECURITY_HEADERS, canonical, etag, parseIfMatch, readJson, send, sendError } from "./http.js";
import { ENTRY_COOKIE, LAUNCH_RE, SCRIPT_PATH, ShareContextScript, TOKEN_RE, cleanTarget, injectHead, isDocumentPath, readToken, recoveryPage, scriptTag, targetPath } from "./share-context.js";

const LIMITS = { wallMs: 5000, cpuMs: 1000, queueMs: 1000, maxDbCalls: 20, maxResponseBytes: 256 * 1024, memoryBytes: 32 * 1024 * 1024, stackBytes: 512 * 1024 };
// Scripts stay the app's own. Inline styles and images from any https host
// (map tiles, avatars) are allowed, as in HTML bundles: the app runs on its
// own origin, so neither reaches anything of ICS. Requests the script reads (fetch,
// vector tiles) go only to the hosts the release declares in
// `frontend.connect`, so every way out is visible in the version history.
const CSP_BASE = "default-src 'none'; script-src 'self'; worker-src 'self' blob:; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; font-src 'self' data:; media-src 'self' data: blob: https:; form-action 'self'; frame-ancestors 'none'; base-uri 'none'";

/** The page CSP of a release: the base policy plus its declared hosts. */
export function contentSecurityPolicy(manifest) {
  const hosts = (manifest?.frontend?.connect ?? []).map((h) => ` https://${h}`).join("");
  return `${CSP_BASE}; connect-src 'self'${hosts}`;
}
const MIME = { html: "text/html; charset=utf-8", htm: "text/html; charset=utf-8", js: "text/javascript; charset=utf-8", mjs: "text/javascript; charset=utf-8", css: "text/css; charset=utf-8", json: "application/json", svg: "image/svg+xml", png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg", gif: "image/gif", webp: "image/webp", ico: "image/x-icon", woff2: "font/woff2", txt: "text/plain; charset=utf-8" };
const IDEMPOTENCY_KEY_RE = /^[A-Za-z0-9._:-]{8,128}$/;

/** A local path to land on after the sign-in; anything else is `/`. */
function safeBack(back) {
  if (typeof back !== "string" || !back.startsWith("/")) return "/";
  return cleanTarget(back.slice(1)) === null && back !== "/" ? "/" : back;
}

export class Gateway {
  constructor({ config, ics, apps, pools, runners, limiter = new RateLimiter(), hosts = new HostResolver({ config, ics }) }) {
    this.config = config;
    this.ics = ics;
    this.hosts = hosts;
    this.apps = apps;
    this.pools = pools;
    this.runners = runners;
    this.limiter = limiter;
    this.shareScript = new ShareContextScript(ics);
  }

  // Runs on the session cookie alone, before ICS is asked anything, so a
  // flood is stopped here and not in the backend.
  async rateLimit(target, session) {
    const { userPerSecond = 20, linkPerSecond = 100 } = this.config.rateLimits ?? {};
    const buckets = [{ key: `${target.assetHex}:${session.uid}`, burst: userPerSecond * 2, perSecond: userPerSecond }];
    // A link visitor can mint a new identity by dropping the cookie, so the
    // whole link also has one (larger) budget.
    if (session.sh) buckets.push({ key: `${target.assetHex}:share:${session.sh}`, burst: linkPerSecond * 2, perSecond: linkPerSecond });
    if (!(await this.limiter.take(buckets))) throw new HttpError(429, "rate_limited", "too many requests", { retryAfter: 1 });
  }

  /**
   * The access check of every request and realtime socket of an app:
   * `{auth, app, bundle, model}` or an HttpError. `token`: a share link
   * named in the page address; another link than the session's (or a dead
   * one) throws with `reenter`, a new entry through that link.
   */
  async admit(target, session, token = null) {
    const auth = await this.ics.authorize(target.assetHex, target.environment, session.uid, session.sh ?? null, token);
    if (!auth.found || auth.deleted) throw new HttpError(404, "not_found", "application not found");
    // A member keeps their own session.
    if (token && (!auth.share_token_id || (session.sh && auth.share_token_id !== session.sh))) throw new HttpError(400, "launch_invalid", "another share link", { reenter: true });
    if (!auth.app_use || !auth.user) throw new HttpError(403, "forbidden", "you no longer have access to this application");
    const app = this.apps.get(target.assetHex, target.environment);
    await this.apps.sync(app, auth);
    if (auth.desired_state !== "enabled" || app.blocked) throw new HttpError(503, "app_suspended", "the application is suspended");
    if (!auth.release) throw new HttpError(503, "app_not_ready", "the application has no active release");
    app.releaseId = auth.release.id;
    const { bundle, model } = await this.apps.model(auth.release.id);
    return { auth, app, bundle, model };
  }

  async handle(req, res) {
    const requestId = `req_${crypto.randomBytes(9).toString("base64url")}`;
    try {
      const target = await this.hosts.resolve(req.headers.host);
      if (!target) throw new HttpError(404, "not_found", "unknown application host");
      let url;
      try {
        url = new URL(req.url, `https://${target.host}`);
      } catch {
        throw new HttpError(400, "bad_request", "bad URL");
      }
      if (url.pathname === "/__ics/sdk.js") return this.sdk(res);
      if (url.pathname === SCRIPT_PATH) return await this.shareContextScript(req, res);
      if (url.pathname === "/__ics/callback") return await this.callback(req, res, target, url);
      if (url.pathname === "/__ics/share") return this.startShare(res, target, url);
      if (url.pathname === "/__ics/login") return this.startLogin(res, target, `/${cleanTarget(url.searchParams.get("to")) ?? ""}`);
      const cookies = parseCookies(req.headers.cookie);
      const session = readSession(this.config.sessionSecret, cookies[SESSION_COOKIE], target);
      const isApi = url.pathname.startsWith("/api/");
      // A page load (not the app's own files or data): the one place the
      // link named in the address is checked against the session.
      const page = (req.method === "GET" || req.method === "HEAD") && isDocumentPath(url.pathname);
      if (!session) {
        if (isApi) throw new HttpError(401, "app_session_required", "open the application through ICS to sign in");
        // The entry page keeps the whole address, fragment included, which
        // a redirect through the sign-in would lose.
        if (page) return recoveryPage(res, target, url);
        return this.startLogin(res, target, url.pathname + url.search);
      }
      if (url.pathname === "/__ics/logout" && req.method === "POST") {
        this.checkWrite(req, target, session);
        return send(res, 204, undefined, { "set-cookie": cookie(SESSION_COOKIE, "", { maxAge: 0 }) });
      }
      const named = page ? readToken(url.search) : { state: "none", token: null };
      if (named.state === "invalid") return recoveryPage(res, target, url, 400);
      await this.rateLimit(target, session);
      let admitted;
      try {
        admitted = await this.admit(target, session, named.token);
      } catch (err) {
        if (err?.reenter) return recoveryPage(res, target, url);
        throw err;
      }
      const { auth, app, bundle, model } = admitted;
      const rc = { req, res, url, target, session, cookies, auth, app, bundle, model, requestId, permissions: new Set(auth.permissions) };
      if (!isApi) return await this.serveStatic(rc);
      return await this.api(rc);
    } catch (err) {
      const e = err instanceof HttpError || err instanceof DataError || err instanceof ValidationError ? err : err?.status ? err : mapPgError(err);
      if (!e.status || e.status >= 500) process.stderr.write(`${JSON.stringify({ event: "request_failed", requestId, code: e.code, error: String(err?.cause?.message ?? err?.message) })}\n`);
      if (err instanceof ValidationError) err.status = 422;
      return sendError(res, e, requestId);
    }
  }

  sdk(res) {
    res.writeHead(200, { ...SECURITY_HEADERS, "content-type": "text/javascript; charset=utf-8", "cache-control": "no-cache" });
    res.end(SDK_SOURCE);
  }

  async shareContextScript(req, res) {
    const { body, etag } = await this.shareScript.get();
    const headers = { ...SECURITY_HEADERS, "content-type": "text/javascript; charset=utf-8", "cache-control": "no-cache", ...(etag ? { etag } : {}) };
    if (etag && req.headers["if-none-match"] === etag) {
      res.writeHead(304, headers);
      return res.end();
    }
    res.writeHead(200, headers);
    res.end(body);
  }

  startLogin(res, target, back) {
    const nonce = newStartNonce();
    const value = `${nonce}.${Buffer.from(safeBack(back)).toString("base64url")}`;
    const launch = new URL("/api/micro-applications/launch", target.icsBaseUrl ?? this.config.icsPublicBaseUrl);
    launch.searchParams.set("host", target.host);
    launch.searchParams.set("state", stateOf(nonce));
    res.writeHead(302, { ...SECURITY_HEADERS, location: launch.toString(), "set-cookie": cookie(START_COOKIE, value, { maxAge: 300 }), "cache-control": "no-store" });
    res.end();
  }

  startShare(res, target, url) {
    // A share link opens the app through ICS, which checks the link's gate
    // (password, sign-in) on its own origin and answers with a code. A member
    // gets a code of their own there, so the link never demotes them to an
    // anonymous visitor. The page the visit started on comes back with the
    // link in its address.
    const token = url.searchParams.get("token") ?? "";
    if (!TOKEN_RE.test(token)) throw new HttpError(400, "launch_invalid", "invalid share link");
    const to = cleanTarget(url.searchParams.get("to"));
    const nonce = newStartNonce();
    const launch = new URL(`/api/share/${token}/launch`, target.icsBaseUrl ?? this.config.icsPublicBaseUrl);
    launch.searchParams.set("host", target.host);
    launch.searchParams.set("state", stateOf(nonce));
    if (to) launch.searchParams.set("to", to);
    const back = targetPath(to ?? "", token);
    res.writeHead(302, { ...SECURITY_HEADERS, location: launch.toString(), "referrer-policy": "no-referrer", "set-cookie": cookie(START_COOKIE, `${nonce}.${Buffer.from(back).toString("base64url")}`, { maxAge: 300 }), "cache-control": "no-store" });
    res.end();
  }

  async callback(req, res, target, url) {
    const code = url.searchParams.get("code");
    const cookies = parseCookies(req.headers.cookie);
    const start = cookies[START_COOKIE];
    if (!code || !start) throw new HttpError(400, "launch_invalid", "the sign-in did not start in this browser");
    const [nonce, back64] = start.split(".");
    const result = await this.ics.exchangeLaunch(code, target.host, stateOf(nonce));
    if (result.asset_hex !== target.assetHex || result.environment !== target.environment) throw new HttpError(400, "launch_invalid", "code for another application");
    let userId = result.user_id;
    const shareId = result.share_id ?? null;
    if (shareId) {
      // An anonymous link visitor: keep the identity of an earlier visit
      // through the same link, so their own records stay theirs.
      const prior = readSession(this.config.sessionSecret, cookies[SESSION_COOKIE], target);
      userId = prior?.sh === shareId ? prior.uid : crypto.randomUUID();
    }
    const { value, payload } = issueSession(this.config.sessionSecret, { userId, assetHex: target.assetHex, environment: target.environment, host: target.host, shareId });
    const back = safeBack(Buffer.from(back64 ?? "", "base64url").toString());
    const maxAge = payload.exp - Math.floor(Date.now() / 1000);
    const setCookies = [cookie(SESSION_COOKIE, value, { maxAge }), cookie(START_COOKIE, "", { maxAge: 0 })];
    // A launch of the member's own (from the panel or a sign-in): the next
    // page drops the tab's earlier link context, once.
    if (!shareId) setCookies.push(cookie(ENTRY_COOKIE, crypto.randomBytes(12).toString("base64url"), { maxAge: 60 }));
    res.writeHead(302, { ...SECURITY_HEADERS, location: back, "cache-control": "no-store", "set-cookie": setCookies });
    res.end();
  }

  async serveStatic(rc) {
    const { url, bundle, auth, res } = rc;
    if (rc.req.method !== "GET" && rc.req.method !== "HEAD") throw new HttpError(405, "method_not_allowed", "method not allowed");
    let rel = decodeURIComponent(url.pathname);
    if (rel === "/" || rel === "") rel = bundle.manifest.frontend.entry.slice("public/".length);
    else rel = rel.slice(1);
    if (rel.includes("..") || rel.includes("\\") || rel.includes("\0")) throw new HttpError(404, "not_found", "not found");
    const path = `public/${rel}`;
    if (!bundle.public_files.includes(path)) throw new HttpError(404, "not_found", "not found");
    const file = await this.ics.publicFile(auth.release.id, path);
    if (!file) throw new HttpError(404, "not_found", "not found");
    const ext = path.split(".").pop().toLowerCase();
    const isHtml = ext === "html" || ext === "htm";
    const headers = {
      ...SECURITY_HEADERS,
      "content-type": MIME[ext] ?? "application/octet-stream",
      "content-security-policy": contentSecurityPolicy(bundle.manifest),
      "cache-control": isHtml ? "no-store" : "private, max-age=60",
      "x-ics-release": auth.release.id,
    };
    let bytes = file.bytes;
    if (isHtml && auth.share_context) {
      const launch = rc.cookies[ENTRY_COOKIE];
      const direct = typeof launch === "string" && LAUNCH_RE.test(launch);
      bytes = injectHead(bytes, scriptTag({ assetId: rc.target.assetHex, kind: "micro_application", scope: "/", entryMode: direct ? "direct" : "continuation", launch: direct ? launch : null }));
      if (launch !== undefined) headers["set-cookie"] = cookie(ENTRY_COOKIE, "", { maxAge: 0 });
    }
    headers["content-length"] = String(bytes.length);
    res.writeHead(200, headers);
    res.end(rc.req.method === "HEAD" ? undefined : bytes);
  }

  checkWrite(req, target, session) {
    // Same-site does not protect sibling app origins: exact Origin plus a
    // token bound to this session.
    if (req.headers.origin !== `https://${target.host}`) throw new HttpError(403, "csrf_failed", "cross-origin write refused");
    if (!checkCsrf(this.config.sessionSecret, session, req.headers["x-ics-csrf"])) throw new HttpError(403, "csrf_failed", "missing or invalid CSRF token");
  }

  async api(rc) {
    const { req, url } = rc;
    const path = url.pathname.slice("/api".length);
    const method = req.method;
    if (method === "GET" && path === "/v1/session") return this.sessionInfo(rc);
    if (method === "GET" && path === "/v1/schema") return send(rc.res, 200, publicSchema(rc));
    if (method === "GET" && path === "/v1/openapi.json") return send(rc.res, 200, buildOpenApi(rc));
    const crud = /^\/v1\/collections\/([a-z][a-z0-9_]{0,47})(?:\/([^/]+))?$/.exec(path);
    if (crud) return this.crud(rc, crud[1], crud[2] ? decodeURIComponent(crud[2]) : null);
    if (path.startsWith("/v1/custom/")) {
      const match = rc.model.matchEndpoint(method, path);
      if (!match) throw new HttpError(404, "not_found", "no such endpoint");
      return this.custom(rc, match.endpoint, match.params);
    }
    throw new HttpError(404, "not_found", "no such endpoint");
  }

  sessionInfo(rc) {
    const { auth, session } = rc;
    send(rc.res, 200, {
      user: { id: auth.user.id, displayName: auth.user.display_name, email: auth.user.email, guest: Boolean(session.sh) },
      app: { id: auth.asset_id, title: auth.title, environment: rc.target.environment, release: auth.release.id, dataGeneration: auth.data_generation },
      permissions: [...rc.permissions].sort(),
      roles: auth.roles ?? [],
      csrfToken: csrfToken(this.config.sessionSecret, session),
      requestId: rc.requestId,
    });
  }

  ctxFor(rc, binding) {
    return {
      assetId: rc.auth.asset_id,
      environment: rc.target.environment,
      dataGeneration: rc.auth.data_generation,
      actorId: rc.auth.user.id,
      requestId: rc.requestId,
      releaseId: rc.auth.release.id,
      schema: binding.schema,
      cursorSecret: this.config.sessionSecret,
      // The owner's data quota is full: reads and deletes still work.
      dataFull: Boolean(rc.auth.data_quota?.exceeded),
    };
  }

  mutationPreconditions(rc) {
    const { req } = rc;
    this.checkWrite(req, rc.target, rc.session);
    const gen = req.headers["x-ics-data-generation"];
    if (gen === undefined) throw new HttpError(428, "precondition_required", "X-ICS-Data-Generation is required");
    if (String(rc.auth.data_generation) !== String(gen)) throw new HttpError(409, "data_generation_changed", "the data was restored; reload the application");
  }

  checkRelease(rc) {
    const release = rc.req.headers["x-ics-release"];
    if (!release) throw new HttpError(428, "precondition_required", "X-ICS-Release is required");
    if (release !== rc.auth.release.id) throw new HttpError(409, "release_changed", "a new version of the application is active; reload it");
  }

  idempotencyKey(rc, required) {
    const key = rc.req.headers["idempotency-key"];
    if (key === undefined) {
      if (required) throw new HttpError(428, "precondition_required", "Idempotency-Key is required");
      return null;
    }
    if (!IDEMPOTENCY_KEY_RE.test(key)) throw new HttpError(400, "invalid_idempotency_key", "Idempotency-Key must be 8-128 safe characters");
    return key;
  }

  /**
   * Run a mutation in one transaction with the idempotency reservation in
   * front of it. Returns {status, body, headers} and sends it.
   */
  async mutate(rc, { routeKey, key, bodyForHash, ifRevision, readOnly = false, run }) {
    const binding = await this.apps.binding(rc.app, rc.auth.credential_generation);
    const ctx = this.ctxFor(rc, binding);
    const requestHash = crypto
      .createHash("sha256")
      .update(canonical([rc.req.method, rc.url.pathname, bodyForHash ?? null, ifRevision ?? null]))
      .digest("hex");
    const checkRelease = () => this.checkRelease(rc);
    const outcome = await this.transact(rc, binding, ctx, { routeKey, key, requestHash, readOnly, checkRelease, run });
    const headers = { ...(outcome.headers ?? {}) };
    if (outcome.replay) headers["idempotent-replayed"] = "true";
    send(rc.res, outcome.status, outcome.status === 204 ? undefined : outcome.body, headers);
  }

  /**
   * The transaction behind `mutate`, without sending: the idempotency key (if
   * any) is reserved in the same transaction as the change and its result,
   * so a retry after a lost answer or an unknown commit replays the stored
   * result and never writes twice. Also used by the broker admin API.
   */
  async transact(rc, binding, ctx, { routeKey, key, requestHash, readOnly = false, checkRelease, run }) {
    const schema = binding.schema;
    const deadline = Date.now() + (rc.limits?.wallMs ?? LIMITS.wallMs);
    const abort = new AbortController();
    const timer = setTimeout(() => abort.abort(), Math.max(0, deadline - Date.now()));
    timer.unref();
    // Collections the writes below touch (data.js adds to it).
    const changed = new Set();
    ctx.changed = changed;
    this.apps.begin(rc.app, !rc.platform);
    try {
      const outcome = await inTransaction(this.pools, rc.app.key, binding, { readOnly, statementTimeoutMs: Math.min(2000, deadline - Date.now()), signal: abort.signal }, async (client) => {
        if (rc.app.blocked) throw new HttpError(503, "app_suspended", "the application is suspended");
        if (key) {
          const table = `${quoteIdent(schema)}."_ics_idempotency"`;
          await client.query(`DELETE FROM ${table} WHERE data_generation = $1 AND actor = $2 AND route = $3 AND key = $4 AND created_at < now() - interval '24 hours'`, [ctx.dataGeneration, ctx.actorId, routeKey, key]);
          const reserved = await client.query(
            `INSERT INTO ${table} (data_generation, actor, route, key, request_hash, release_id) VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT DO NOTHING RETURNING key`,
            [ctx.dataGeneration, ctx.actorId, routeKey, key, requestHash, ctx.releaseId],
          );
          if (reserved.rowCount === 0) {
            const prior = await client.query(`SELECT request_hash, status, response, headers FROM ${table} WHERE data_generation = $1 AND actor = $2 AND route = $3 AND key = $4`, [ctx.dataGeneration, ctx.actorId, routeKey, key]);
            const row = prior.rows[0];
            if (!row || row.request_hash !== requestHash) throw new HttpError(409, "idempotency_key_reused", "this Idempotency-Key was used with a different request");
            return { replay: true, status: row.status, body: row.response, headers: row.headers ?? {} };
          }
          checkRelease?.();
          const result = await run(client, ctx);
          if (rc.app.blocked) throw new HttpError(503, "app_suspended", "the application is suspended");
          await client.query(`UPDATE ${table} SET status = $5, response = $6, headers = $7 WHERE data_generation = $1 AND actor = $2 AND route = $3 AND key = $4`, [
            ctx.dataGeneration,
            ctx.actorId,
            routeKey,
            key,
            result.status,
            JSON.stringify(result.body ?? null),
            JSON.stringify(result.headers ?? {}),
          ]);
          return result;
        }
        if (!readOnly) checkRelease?.();
        const result = await run(client, ctx);
        if (rc.app.blocked && !readOnly) throw new HttpError(503, "app_suspended", "the application is suspended");
        return result;
      });
      if (changed.size) this.apps.markChanged(rc.app, changed, routeKey);
      return outcome;
    } catch (err) {
      if (err?.code === "execution_deadline" || err?.code === "commit_unknown") this.apps.recordFailure(rc.app, ctx.releaseId, err.code, rc.requestId);
      // The commit may have happened: a needless refetch beats a missed change.
      if (err?.code === "commit_unknown" && changed.size) this.apps.markChanged(rc.app, changed, routeKey);
      throw err;
    } finally {
      clearTimeout(timer);
      this.apps.end(rc.app, !rc.platform);
    }
  }

  async read(rc, fn, { snapshot = false } = {}) {
    const binding = await this.apps.binding(rc.app, rc.auth.credential_generation);
    const ctx = this.ctxFor(rc, binding);
    this.apps.begin(rc.app, !rc.platform);
    try {
      return await inTransaction(this.pools, rc.app.key, binding, { readOnly: true, snapshot, statementTimeoutMs: 2000 }, (client) => fn(client, ctx));
    } finally {
      this.apps.end(rc.app, !rc.platform);
    }
  }

  async crud(rc, collectionName, id) {
    const { req, res, model } = rc;
    const collection = model.collection(collectionName);
    const rule = (op) => {
      const r = data.crudRule(collection, op);
      if (!r) throw new HttpError(405, "operation_not_available", "this operation is not offered for the collection");
      data.assertPermission(r, rc.permissions);
      return r;
    };
    const getRule = data.crudRule(collection, "get");
    const projectionFor = () => (getRule && rc.permissions.has(getRule.permission) ? getRule.readFields ?? collection.allFields() : ["id", "revision"]);

    if (req.method === "GET" && !id) {
      const r = rule("list");
      const params = Object.fromEntries(rc.url.searchParams);
      const { limit, cursor, sort, ...rest } = params;
      const filters = Object.entries(rest).map(([field, value]) => ({ field, op: "eq", value: this.coerceFilter(collection, field, value) }));
      const query = { filters, sort, cursor, limit: limit === undefined ? undefined : Number(limit) };
      const page = await this.read(rc, (client, ctx) => data.list(client, ctx, collection, r, query));
      return send(res, 200, { ...page, release: rc.auth.release.id, requestId: rc.requestId });
    }
    if (req.method === "GET" && id) {
      const r = rule("get");
      const row = await this.read(rc, (client, ctx) => data.get(client, ctx, collection, r, id));
      if (!row) throw new HttpError(404, "not_found", "record not found");
      return send(res, 200, row, row.revision ? { etag: etag(row.revision) } : {});
    }
    if (req.method === "POST" && !id) {
      const r = rule("create");
      this.mutationPreconditions(rc);
      const key = this.idempotencyKey(rc, true);
      const body = await readJson(req);
      const ret = projectionFor();
      return this.mutate(rc, {
        routeKey: `POST /v1/collections/${collection.name}`,
        key,
        bodyForHash: body,
        run: async (client, ctx) => {
          const row = await data.insert(client, ctx, collection, r, body, { returnFields: [...new Set(["id", "revision", ...ret])] });
          return { status: 201, body: row, headers: { location: `/api/v1/collections/${collection.name}/${row.id}`, etag: etag(row.revision) } };
        },
      });
    }
    if (req.method === "PATCH" && id) {
      const r = rule("update");
      this.mutationPreconditions(rc);
      const ifRevision = parseIfMatch(req.headers["if-match"]);
      if (ifRevision === undefined) throw new HttpError(428, "precondition_required", "If-Match is required");
      const key = this.idempotencyKey(rc, false);
      const body = await readJson(req);
      const ret = projectionFor();
      return this.mutate(rc, {
        routeKey: `PATCH /v1/collections/${collection.name}/:id`,
        key,
        bodyForHash: body,
        ifRevision,
        run: async (client, ctx) => {
          const row = await data.update(client, ctx, collection, r, id, body, ifRevision, { returnFields: [...new Set(["id", "revision", ...ret])] });
          return { status: 200, body: row, headers: { etag: etag(row.revision) } };
        },
      });
    }
    if (req.method === "DELETE" && id) {
      const r = rule("delete");
      this.mutationPreconditions(rc);
      const ifRevision = parseIfMatch(req.headers["if-match"]);
      if (ifRevision === undefined) throw new HttpError(428, "precondition_required", "If-Match is required");
      const key = this.idempotencyKey(rc, true);
      return this.mutate(rc, {
        routeKey: `DELETE /v1/collections/${collection.name}/:id`,
        key,
        ifRevision,
        run: async (client, ctx) => {
          await data.remove(client, ctx, collection, r, id, ifRevision);
          return { status: 204 };
        },
      });
    }
    throw new HttpError(405, "method_not_allowed", "method not allowed");
  }

  coerceFilter(collection, field, value) {
    const type = collection.fieldType(field);
    if (!type) throw new ValidationError(`/${field}`, "unknown filter field");
    if (type.type === "integer") return Number(value);
    if (type.type === "boolean") return value === "true";
    return value;
  }

  /** The checks every custom endpoint passes first; sets `rc.limits`. The
   * document view serves readers with different permissions (it leaves out
   * what they cannot see), so its capabilities are checked on each data
   * call, as for every handler, instead of all up front. */
  prepareCustom(rc, endpoint) {
    data.assertPermission({ permission: endpoint.permission }, rc.permissions);
    if (endpoint.name !== rc.bundle.manifest.document?.endpoint) {
      for (const capName of endpoint.capabilities) {
        const cap = rc.model.capabilities[capName];
        if (!cap || !rc.permissions.has(cap.permission)) throw new HttpError(403, "forbidden", "operation not permitted");
      }
    }
    if (this.apps.breakerOpen(rc.app)) throw new HttpError(503, "circuit_open", "the application is failing repeatedly; try again shortly", { retryAfter: 30 });
    const limits = { ...LIMITS };
    const requested = rc.bundle.manifest.limitsRequested ?? {};
    for (const k of ["wallMs", "maxDbCalls", "maxResponseBytes"]) if (requested[k] && requested[k] < limits[k]) limits[k] = requested[k];
    rc.limits = limits;
  }

  /** A read-only endpoint in one read-only transaction; `{ status, body }`. */
  async runReadOnly(rc, endpoint, input) {
    const { app, limits } = rc;
    this.apps.begin(app, !rc.platform);
    try {
      const binding = await this.apps.binding(app, rc.auth.credential_generation);
      const ctx = this.ctxFor(rc, binding);
      const deadline = Date.now() + limits.wallMs;
      const abort = new AbortController();
      const timer = setTimeout(() => abort.abort(), limits.wallMs);
      timer.unref();
      try {
        return await inTransaction(this.pools, app.key, binding, { readOnly: true, statementTimeoutMs: Math.min(2000, deadline - Date.now()), signal: abort.signal }, (client) =>
          this.invokeHandler(rc, endpoint, input, undefined, client, ctx, limits));
      } finally {
        clearTimeout(timer);
      }
    } finally {
      this.apps.end(app, !rc.platform);
    }
  }

  async custom(rc, endpoint, params) {
    const { req } = rc;
    this.prepareCustom(rc, endpoint);
    const { limits } = rc;

    const query = coerceQuery(endpoint.input.query ?? { type: "object", properties: {} }, Object.fromEntries(rc.url.searchParams));
    const input = { params, query, body: null };
    validate(endpoint.input.params ?? { type: "object", additionalProperties: false, properties: {} }, params, "/params");
    validate(endpoint.input.query ?? { type: "object", additionalProperties: false, properties: {} }, query, "/query");
    const readOnly = endpoint.transaction === "read_only";
    let ifRevision;
    let key = null;
    if (!readOnly) {
      this.mutationPreconditions(rc);
      const body = await readJson(req);
      if (endpoint.input.body) validate(endpoint.input.body, body, "/body");
      input.body = body;
      ifRevision = parseIfMatch(req.headers["if-match"]);
      if (endpoint.ifMatch === "required" && ifRevision === undefined) throw new HttpError(428, "precondition_required", "If-Match is required");
      key = this.idempotencyKey(rc, endpoint.idempotency === "required");
    }
    if (readOnly) {
      const out = await this.runReadOnly(rc, endpoint, input);
      return send(rc.res, out.status, out.body);
    }
    const run = (client, ctx) => this.invokeHandler(rc, endpoint, input, ifRevision, client, ctx, limits);
    return this.mutate(rc, { routeKey: `${endpoint.method} ${endpoint.path}`, key, bodyForHash: input.body, ifRevision, run });
  }

  invokeHandler(rc, endpoint, input, ifRevision, client, ctx, limits) {
    return invokeHandler(this, rc, endpoint, input, ifRevision, client, ctx, limits);
  }

}
