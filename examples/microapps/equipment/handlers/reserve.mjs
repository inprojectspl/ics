// POST /api/v1/custom/reservations
// Takes stock from the equipment row and inserts the reservation in one
// transaction. The stock update is conditional on the equipment revision
// just read (and on active=true, enforced by the capability), so two
// concurrent bookings cannot both take the last unit; a failure after the
// stock update rolls the whole request back.
export default async function reserve(input, ctx) {
  const { equipmentId, startsOn, endsOn, quantity, note } = input.body;
  if (endsOn < startsOn) throw ctx.errors.invalid("ends_before_start");
  const item = await ctx.db.get("equipment", equipmentId, { capability: "equipment.for_booking", forUpdate: true });
  if (!item || !item.active) throw ctx.errors.notFound();
  if (item.available < quantity) throw ctx.errors.conflict("not_enough_available");
  const stock = await ctx.db.update("equipment", item.id, { available: item.available - quantity }, {
    capability: "equipment.take_stock",
    ifRevision: item.revision,
  });
  const reservation = await ctx.db.insert("reservations", {
    equipment_id: item.id,
    starts_on: startsOn,
    ends_on: endsOn,
    quantity,
    note: note ?? "",
  }, { capability: "reservations.create_own" });
  ctx.log("info", "reserved", { equipment: item.id, quantity });
  return { status: 201, body: { reservation, available: stock.available } };
}
