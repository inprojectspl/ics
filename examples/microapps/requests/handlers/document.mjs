// GET /api/v1/custom/document: the register read as a document (ics_asset_read).
// Shows each reader what the app shows them: their own requests and, for a
// reviewer, the queue waiting for approval.
const STATUS = { submitted: "submitted", approved: "approved" };
const cell = (v) => String(v ?? "").replace(/\s+/g, " ").replace(/\|/g, "\\|");

// Every record a capability lists, page by page (at most 1000).
async function all(ctx, collection, capability, query = {}) {
  const items = [];
  let cursor;
  do {
    const page = await ctx.db.list(collection, { ...query, limit: 200, cursor }, { capability });
    items.push(...page.items);
    cursor = page.nextCursor;
  } while (cursor && items.length < 1000);
  return items;
}

export default async function document(input, ctx) {
  const can = new Set(ctx.actor.permissions);
  const lines = ["# Request register", ""];
  if (can.has("requests.read")) {
    const mine = await all(ctx, "requests", "requests.list_own", { sort: "-created_at" });
    lines.push("## My requests", "");
    if (!mine.length) lines.push("_No requests._", "");
    else lines.push("| Title | Status | Submitted |", "|---|---|---|", ...mine.map((r) => `| ${cell(r.title)} | ${STATUS[r.status] ?? r.status} | ${r.created_at.slice(0, 10)} |`), "");
  }
  if (can.has("requests.approve")) {
    const queue = await all(ctx, "requests", "requests.review_queue");
    lines.push("## To approve", "");
    if (!queue.length) lines.push("_Nothing waits._", "");
    else lines.push("| Title | Description |", "|---|---|", ...queue.map((r) => `| ${cell(r.title)} | ${cell(r.description)} |`), "");
  }
  return { status: 200, body: { markdown: lines.join("\n") } };
}
