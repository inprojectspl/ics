// POST /api/v1/custom/requests/:id/approve
// A reviewer approves someone else's submitted request. The broker enforces
// the same rules again (requests.approve: not_own, status=submitted, only the
// status field, revision from If-Match); these checks give clear errors.
export default async function approve(input, ctx) {
  const item = await ctx.db.get("requests", input.params.id, { capability: "requests.review" });
  if (!item) throw ctx.errors.notFound();
  if (item.created_by === ctx.actor.id) throw ctx.errors.forbidden("self_approval");
  if (item.status !== "submitted") throw ctx.errors.conflict("invalid_state");
  const saved = await ctx.db.update("requests", item.id, { status: "approved" }, {
    capability: "requests.approve",
    ifRevision: ctx.request.preconditions.revision,
  });
  ctx.log("info", "request approved", { id: saved.id });
  return { status: 200, body: { id: saved.id, status: saved.status, revision: saved.revision } };
}
