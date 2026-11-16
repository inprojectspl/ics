// POST /api/v1/custom/notes/:id/toggle-pin (If-Match + Idempotency-Key)
export default async function togglePin(input, ctx) {
  const note = await ctx.db.get("notes", input.params.id, { capability: "notes.read_own" });
  if (!note) throw ctx.errors.notFound();
  const saved = await ctx.db.update("notes", note.id, { pinned: !note.pinned }, {
    capability: "notes.pin_own",
    ifRevision: ctx.request.preconditions.revision,
  });
  return { status: 200, body: { id: saved.id, pinned: saved.pinned, revision: saved.revision } };
}
