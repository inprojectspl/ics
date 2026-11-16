// GET /api/v1/custom/review-requests: submitted requests of other people,
// with the id and revision a reviewer needs for If-Match.
export default async function reviewRequests(input, ctx) {
  const query = { limit: input.query.limit ?? 50 };
  if (input.query.cursor) query.cursor = input.query.cursor;
  const page = await ctx.db.list("requests", query, { capability: "requests.review_queue" });
  const body = { items: page.items };
  if (page.nextCursor) body.nextCursor = page.nextCursor;
  return { status: 200, body };
}
