// The broker side of a Google Sheets link (ICS -> broker, private network).
// ICS talks to Google; the broker only reads the linked collection and
// applies the changes a person accepted, as that person, under the same
// rules, row scopes, field lists and revisions as the app's own API.
import crypto from "node:crypto";
import { SHEETS_ORIGIN } from "./apps.js";
import * as data from "./data.js";
import { readerContext } from "./export.js";
import { HttpError, canonical } from "./http.js";

const PAGE = 200;
// ICS sends the app owner's row limit; this caps whatever it sends.
export const MAX_ROWS = 100000;
const DEFAULT_ROWS = 5000;
// The first sync of a sheet creates a record per row, so one apply takes as
// many changes as a sync may read rows.
export const MAX_CHANGES = MAX_ROWS;
// One transaction for all of them: its deadline grows with their number.
export const applyDeadlineMs = (changes) => Math.min(300_000, 20_000 + 20 * changes);

function collectionOf(rc, name) {
  const collection = rc.model.collections.get(name);
  if (!collection) throw new HttpError(404, "collection_not_found", "the linked collection is not in the active release");
  return collection;
}

function ruleFor(rc, collection, op) {
  const rule = data.crudRule(collection, op);
  if (!rule) throw new HttpError(403, "operation_not_available", `the app has no ${op} rule for ${collection.name}`);
  data.assertPermission(rule, rc.permissions);
  return rule;
}

/**
 * Every record of `collection` the person may list (up to `limit`), with
 * `id`, `revision` and the linked `fields`. A field the list rule hides is an
 * error, not a silent gap: the comparison would read it as empty.
 */
export async function readRows(gateway, { assetHex, environment, userId, collection: name, fields, limit }) {
  const max = Number.isInteger(limit) && limit >= 0 ? Math.min(limit, MAX_ROWS) : DEFAULT_ROWS;
  const rc = await readerContext(gateway, { assetHex, environment, userId }, "sht");
  const collection = collectionOf(rc, name);
  const rule = ruleFor(rc, collection, "list");
  const readable = new Set(data.readFieldsOf(rule, collection));
  const hidden = ["id", "revision", ...fields].filter((f) => !readable.has(f));
  if (hidden.length) throw new HttpError(403, "field_not_readable", `the list rule does not show: ${hidden.join(", ")}`);
  const keep = ["id", "revision", ...fields];
  const rows = [];
  let truncated = false;
  await gateway.read(rc, async (client, ctx) => {
    let cursor = null;
    do {
      const page = await data.list(client, ctx, collection, rule, { filters: [], limit: PAGE, sort: "id", cursor });
      // Only what the link needs stays in memory, page by page.
      for (const item of page.items) rows.push(Object.fromEntries(keep.map((f) => [f, item[f] ?? null])));
      cursor = page.nextCursor ?? null;
      if (rows.length > max) {
        truncated = true;
        break;
      }
    } while (cursor);
  });
  return { release: rc.auth.release.id, truncated, rows: rows.slice(0, max) };
}

function checkChanges(changes) {
  if (!Array.isArray(changes) || changes.length === 0) throw new HttpError(400, "bad_request", "changes must be a non-empty array");
  if (changes.length > MAX_CHANGES) throw new HttpError(413, "too_many_changes", `at most ${MAX_CHANGES} changes`);
  for (const c of changes) {
    const isPatch = c?.patch && typeof c.patch === "object";
    if (c?.op === "update" && typeof c.id === "string" && Number.isSafeInteger(c.revision) && isPatch) continue;
    if (c?.op === "create" && typeof c.id === "string" && c.data && typeof c.data === "object") continue;
    throw new HttpError(400, "bad_request", "each change is {op:'update', id, revision, patch} or {op:'create', id, data}");
  }
}

/**
 * Apply `changes` in one transaction, all or nothing, as the person, with
 * `key` (the ICS operation id) reserved in the app's idempotency table: a
 * retry after a lost answer or an unknown commit (`commit_unknown`) replays
 * the stored result and never writes twice. Any other error means the
 * transaction rolled back. ICS names created records (`id`) so it can match
 * them with their sheet rows even before their ids reach the sheet.
 * `release`: the release the preview was made under; another one is active
 * now is `release_changed`.
 */
export async function applyChanges(gateway, { assetHex, environment, userId, collection: name, key, changes, fields = [], release = null }) {
  if (typeof key !== "string" || !/^[A-Za-z0-9._:-]{8,128}$/.test(key)) throw new HttpError(400, "bad_request", "key required");
  checkChanges(changes);
  const rc = await readerContext(gateway, { assetHex, environment, userId }, "sht");
  const collection = collectionOf(rc, name);
  const rules = {
    update: changes.some((c) => c.op === "update") ? ruleFor(rc, collection, "update") : null,
    create: changes.some((c) => c.op === "create") ? ruleFor(rc, collection, "create") : null,
  };
  // A created record comes back with the linked fields the person may read
  // (its defaults among them), so ICS can write them to its new row.
  const listRule = data.crudRule(collection, "list");
  const readable = listRule && rc.permissions.has(listRule.permission) ? new Set(data.readFieldsOf(listRule, collection)) : new Set();
  const createdFields = ["id", "revision", ...fields.filter((f) => readable.has(f) && f !== "id" && f !== "revision")];
  const binding = await gateway.apps.binding(rc.app, rc.auth.credential_generation);
  const ctx = gateway.ctxFor(rc, binding);
  const requestHash = crypto.createHash("sha256").update(canonical([name, changes])).digest("hex");
  const checkRelease = () => {
    if (release && release !== rc.auth.release.id) throw new HttpError(409, "release_changed", "a new release of the app is active since the preview");
  };
  const run = async (client, ctx) => {
    const results = [];
    for (const [index, change] of changes.entries()) {
      try {
        if (change.op === "update") {
          const row = await data.update(client, ctx, collection, rules.update, change.id, change.patch, change.revision, { returnFields: ["id", "revision"] });
          results.push({ id: row.id, revision: row.revision });
        } else {
          const { id, revision, ...values } = await data.insert(client, ctx, collection, rules.create, change.data, { returnFields: createdFields, id: change.id });
          results.push({ id, revision, values });
        }
      } catch (err) {
        err.change = index;
        throw err;
      }
    }
    return { status: 200, body: { release: ctx.releaseId, results } };
  };
  const outcome = await gateway.transact({ ...rc, limits: { wallMs: applyDeadlineMs(changes.length) } }, binding, ctx, { routeKey: SHEETS_ORIGIN, key, requestHash, checkRelease, run });
  return { ...outcome.body, replayed: Boolean(outcome.replay) };
}
