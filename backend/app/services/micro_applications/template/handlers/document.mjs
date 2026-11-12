// GET /api/v1/custom/document: the app read as a document (microapp.json
// "document"). ICS runs it as the reader when an agent reads the app with
// ics_asset_read, so it shows what the app shows that person, records
// filled in. Return Markdown; keep it to what a reader needs.

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
  const notes = await all(ctx, "notes", "notes.list_own", { sort: "-created_at" });
  const lines = ["# Notes", ""];
  for (const n of notes) lines.push(`- ${n.pinned ? "📌 " : ""}${n.text.replace(/\s+/g, " ")} _(${n.created_at.slice(0, 10)})_`);
  if (!notes.length) lines.push("_No notes yet._");
  return { status: 200, body: { markdown: lines.join("\n") } };
}
