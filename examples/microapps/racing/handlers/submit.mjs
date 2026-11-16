// POST /api/v1/custom/results: saves a finished race of three laps after a
// plausibility check (the client is not trusted), then answers with its rank.
//
// The track is 897 m long and the car tops out at 55 m/s on the asphalt, so
// no honest lap is shorter than about 16 s; 13 s leaves room for a perfect line.
const MIN_LAP_MS = 13000;
const MAX_LAP_MS = 15 * 60 * 1000;

export default async function submitResult(input, ctx) {
  const { laps } = input.body;
  const player = input.body.player.replace(/\s+/g, " ").trim().slice(0, 20);
  if (!player) throw ctx.errors.invalid("player_required");
  for (const ms of laps) {
    if (ms < MIN_LAP_MS) throw ctx.errors.invalid("lap_too_fast");
    if (ms > MAX_LAP_MS) throw ctx.errors.invalid("lap_too_slow");
  }
  const total = laps[0] + laps[1] + laps[2];
  const best = Math.min(...laps);
  const saved = await ctx.db.insert("results", {
    player, total_ms: total, lap1_ms: laps[0], lap2_ms: laps[1], lap3_ms: laps[2], best_lap_ms: best,
  }, { capability: "results.submit" });
  const faster = await ctx.db.count("results", [{ field: "total_ms", op: "lt", value: total }], { capability: "results.rank" });
  ctx.log("info", "race saved", { total_ms: total, best_lap_ms: best });
  return { status: 201, body: { id: saved.id, player: saved.player, total_ms: total, best_lap_ms: best, rank: faster + 1 } };
}
