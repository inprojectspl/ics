// GET /api/v1/custom/document: the board as a document, for people and
// agents reading the app (ics_asset_read).
const time = (ms) => {
  const m = Math.floor(ms / 60000);
  return `${m}:${((ms % 60000) / 1000).toFixed(3).padStart(6, "0")}`;
};
const cell = (v) => String(v ?? "").replace(/\s+/g, " ").replace(/\|/g, "\\|");

export default async function document(input, ctx) {
  const races = await ctx.db.list("results", { limit: 10, sort: "total_ms" }, { capability: "results.board" });
  const lap = await ctx.db.list("results", { limit: 1, sort: "best_lap_ms" }, { capability: "results.board" });
  const lines = ["# Race Track", "", "Three laps against the clock on one closed track.", "", "## Fastest drivers", ""];
  if (!races.items.length) lines.push("_Nobody has finished a race yet._", "");
  else lines.push("| Place | Driver | Total | Best lap | Date |", "|---|---|---|---|---|",
    ...races.items.map((r, i) => `| ${i + 1} | ${cell(r.player)} | ${time(r.total_ms)} | ${time(r.best_lap_ms)} | ${r.created_at.slice(0, 10)} |`), "");
  if (lap.items[0]) lines.push(`Fastest lap: ${cell(lap.items[0].player)}, ${time(lap.items[0].best_lap_ms)}.`, "");
  return { status: 200, body: { markdown: lines.join("\n") } };
}
