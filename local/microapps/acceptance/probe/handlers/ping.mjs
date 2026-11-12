export default async function ping(input, ctx) {
  const count = await ctx.db.count("pings", [], { capability: "pings.count_own" });
  return { status: 200, body: { ok: true, count } };
}
