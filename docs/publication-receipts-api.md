# HTML publication receipts

`POST /api/assets/html-json` accepts an optional `publication` object:

```json
{
  "title": "Acceptance report",
  "entry_path": "index.html",
  "files": [{"path": "index.html", "content_text": "<h1>Accepted</h1>"}],
  "publication": {
    "id": "publication-42",
    "order_id": "delivery-17",
    "role": "acceptance-report"
  }
}
```

The authenticated user, optional existing `project_id`, `order_id`, `role`, and
`id` form the publication identity. Clients cannot supply a principal. `id` is
1–200 ASCII letters, digits, dots, underscores, colons or hyphens and starts
with a letter or digit. `order_id` (1–200 characters) and `role` (1–100) contain
no whitespace or ASCII control characters. Unknown fields in `publication`
are rejected. Existing requests without this object retain their behavior.

The first accepted request returns the existing `201` asset result. Repeating
the same identity and payload returns the identical status and body, without
creating another asset, version, share link or audit record and without charging
quota again. The receipt and asset are saved in one PostgreSQL transaction;
an uncommitted operation has no visible receipt. Concurrent identical requests
serialize before staging and resolve to the same result.

The server stores a SHA-256 digest with canonical schema version 1. Inputs are
the operation (`create_html`), title, entry path, effective share mode, project,
normalized tags, doc type, normalized summary and its transport-derived source,
and each file's path, bytes digest and MIME declaration. Files are sorted by
path. Equivalent text/base64 bytes, file order, omitted/null/default share mode,
and existing summary normalization do not change identity. Generated IDs, times,
security scan results and current quotas are excluded. Another semantic payload
under the same key returns `409 publication_conflict`.

After a timeout or lost response, retrieve the committed result:

```http
GET /api/assets/publications/publication-42?order_id=delivery-17&role=acceptance-report
```

Supply `project_id` as a query parameter when it was part of the creation.
The `200` response contains `publication_id`, `project_id`, `order_id`, `role`,
`schema_version`, `payload_hash`, `asset_id`, `version` (currently 1), and `result`
(the original POST response). Both lookup and replay require the original
principal and current access to the asset; project-scoped operations also require
current contributor rights in that project. Another principal receives
`404 publication_not_found`, even if the asset itself is publicly shared.

A missing receipt can mean the request is still in flight or did not commit.
Retry the same key to reconcile it. Do not create a new key merely because the
response was lost. A failure after commit leaves the receipt readable; notification
and outline enqueue remain existing post-commit effects, and receipt replay does
not replay those effects.

Deleting the asset consumes the key permanently: read and replay refuse while
the result is unavailable; neither recreates the asset. The receipt preserves the
original project scope when a project or asset is removed or moved. There is no
expiry or recovery operation for consumed keys.

This API covers initial JSON HTML creation. Next-version publication, CAS and
MCP client propagation are separate changes (#2352 and the associated CAS tasks).
The stored version and original result allow that later API to reuse receipts
without claiming that version creation is implemented here.
