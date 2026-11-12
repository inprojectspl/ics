// GET /api/v1/custom/document: the catalogue and the reader's own
// reservations, read as a document (ics_asset_read).
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
  const catalog = await all(ctx, "equipment", "equipment.catalog");
  const names = new Map(catalog.map((e) => [e.id, e.name]));
  const lines = ["# Rezerwacje sprzętu", "", "## Katalog", ""];
  if (!catalog.length) lines.push("_Katalog jest pusty._", "");
  else lines.push("| Sprzęt | Kategoria | Dostępne | Razem |", "|---|---|---|---|",
    ...catalog.filter((e) => e.active).map((e) => `| ${cell(e.name)} | ${cell(e.category)} | ${e.available} | ${e.quantity} |`), "");
  if (can.has("reservations.read")) {
    const mine = await all(ctx, "reservations", "reservations.mine");
    lines.push("## Moje rezerwacje", "");
    if (!mine.length) lines.push("_Brak rezerwacji._", "");
    else lines.push("| Sprzęt | Od | Do | Sztuk | Stan |", "|---|---|---|---|---|",
      ...mine.map((r) => `| ${cell(names.get(r.equipment_id) ?? r.equipment_id)} | ${r.starts_on} | ${r.ends_on} | ${r.quantity} | ${r.status} |`), "");
  }
  return { status: 200, body: { markdown: lines.join("\n") } };
}
