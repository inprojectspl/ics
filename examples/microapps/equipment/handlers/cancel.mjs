// POST /api/v1/custom/reservations/:id/cancel (If-Match: the reservation's revision)
// Marks the caller's active reservation cancelled and returns the units to
// the equipment stock, atomically.
export default async function cancel(input, ctx) {
  const r = await ctx.db.get("reservations", input.params.id, { capability: "reservations.read_own" });
  if (!r) throw ctx.errors.notFound();
  if (r.status !== "active") throw ctx.errors.conflict("invalid_state");
  const saved = await ctx.db.update("reservations", r.id, { status: "cancelled" }, {
    capability: "reservations.cancel_own",
    ifRevision: ctx.request.preconditions.revision,
  });
  const item = await ctx.db.get("equipment", r.equipment_id, { capability: "equipment.for_booking", forUpdate: true });
  const stock = await ctx.db.update("equipment", item.id, { available: item.available + r.quantity }, {
    capability: "equipment.return_stock",
    ifRevision: item.revision,
  });
  return { status: 200, body: { id: saved.id, status: saved.status, revision: saved.revision, available: stock.available } };
}
