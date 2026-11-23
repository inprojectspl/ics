// What ICS renders when an app is read as a document (the agent reads it as
// Markdown): the app's own document view and the records a person may list.
// Both run as that person, with the same authorization, rules and row scopes
// as the app's own API.
import crypto from "node:crypto";
import * as data from "./data.js";
import { HttpError } from "./http.js";

export async function readerContext(gateway, { assetHex, environment, userId }, prefix) {
  const requestId = `${prefix}_${crypto.randomBytes(9).toString("base64url")}`;
  const auth = await gateway.ics.authorize(assetHex, environment, userId, null);
  if (!auth.found || auth.deleted) throw new HttpError(404, "not_found", "application not found");
  if (!auth.app_use || !auth.user) throw new HttpError(403, "forbidden", "no access to this application");
  if (auth.desired_state !== "enabled") throw new HttpError(503, "app_suspended", "the application is suspended");
  if (!auth.release) throw new HttpError(503, "app_not_ready", "the application has no active release");
  const app = gateway.apps.get(assetHex, environment);
  await gateway.apps.sync(app, auth);
  const { bundle, model } = await gateway.apps.model(auth.release.id);
  // `platform`: ICS reads and writes, never counted as use of the app.
  return { target: { assetHex, environment, host: null }, auth, app, bundle, model, requestId, permissions: new Set(auth.permissions), platform: true };
}

/**
 * The records a person may list and, with `document`, the app's document
 * view (`manifest.document.endpoint`, a read-only endpoint rendering the
 * app's content as Markdown) run as that person: `document` is
 * `{ markdown }` or `{ error }` with the code the app's API would answer, so
 * a failing view never hides the data. One authorization for both.
 */
export async function exportData(gateway, { assetHex, environment, userId, only = null, limit = 50, cursor = null, document = false }) {
  const rc = await readerContext(gateway, { assetHex, environment, userId }, "exp");
  const out = { release: rc.auth.release.id, permissions: [...rc.permissions].sort(), collections: [] };
  if (document && rc.bundle.manifest.document) out.document = await documentView(gateway, rc);
  for (const [name, collection] of rc.model.collections) {
    if (only && name !== only) continue;
    const rule = data.crudRule(collection, "list");
    if (!rule || !rc.permissions.has(rule.permission)) {
      out.collections.push({ name, readable: false, permission: rule?.permission ?? null });
      continue;
    }
    const page = await gateway.read(rc, (client, ctx) => data.list(client, ctx, collection, rule, { filters: [], limit, cursor: only ? cursor : null }));
    out.collections.push({ name, readable: true, items: page.items, next_cursor: page.nextCursor ?? null });
  }
  return out;
}

async function documentView(gateway, rc) {
  const endpoint = rc.model.endpoints.find((e) => e.name === rc.bundle.manifest.document.endpoint);
  try {
    if (!endpoint || endpoint.transaction !== "read_only") throw new HttpError(500, "document_endpoint_invalid", "the document endpoint is missing or writes");
    gateway.prepareCustom(rc, endpoint);
    const out = await gateway.runReadOnly(rc, endpoint, { params: {}, query: {}, body: null });
    if (out.status !== 200 || typeof out.body?.markdown !== "string") throw new HttpError(502, "document_view_failed", `the document view answered ${out.status}`);
    return { markdown: out.body.markdown };
  } catch (e) {
    // Denied, failing or timed out: the code the app's API would answer.
    return { error: typeof e?.code === "string" ? e.code : "document_view_failed" };
  }
}
