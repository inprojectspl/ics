// GET /api/v1/custom/top: the ten fastest races and the fastest single lap.
const row = (r) => ({ id: r.id, revision: r.revision, player: r.player, total_ms: r.total_ms, best_lap_ms: r.best_lap_ms, at: r.created_at });

export default async function top(input, ctx) {
  const races = await ctx.db.list("results", { limit: 10, sort: "total_ms" }, { capability: "results.board" });
  const lap = await ctx.db.list("results", { limit: 1, sort: "best_lap_ms" }, { capability: "results.board" });
  const body = { items: races.items.map(row) };
  if (lap.items[0]) body.best_lap = row(lap.items[0]);
  return { status: 200, body };
}
