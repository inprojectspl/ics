# Publication receipts

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
`schema_version`, `payload_hash`, `asset_id`, `version`, and `result`
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

## Replacing a version

`POST /api/assets/{asset_id}/versions` accepts the same optional `publication`
object encoded as a JSON string in its multipart form. This applies to every
kind already supported by that endpoint (Markdown, HTML and documents). For
example, alongside the uploaded files and their `paths` fields:

```text
publication={"id":"publication-43","order_id":"delivery-17","role":"acceptance-report"}
expected_version=1
```

An authenticated principal, the asset's project (or null), order, role and key
form the same scope as creation. A keyed version write requires a positive
`expected_version`; omitting it returns `422 validation_error`. A new key with
a stale precondition returns `409 version_conflict` before staging. A committed
receipt is resolved before that precondition: retrying the original operation
still returns its original `201` response and version after later versions exist.
The response is saved with AssetVersion and the audit in one database transaction.
There is no separate accepted reservation or second version counter.

The version payload digest covers operation, target asset, expected version,
trimmed change note, kind, effective entry path and the sorted accepted paths
with their bytes digests. Changing any of these semantics under the same key
returns `409 publication_conflict`. File order and an explicit entry matching
the derived entry do not change the digest. Duplicate normalized paths are
rejected for keyed writes. Creation and replacement are distinct operations,
so a creation key cannot also create a subsequent version in the same scope.

Replay requires current write access; receipt GET requires current read access.
Project-scoped requests also retain the original contributor check. Authorization
is refreshed after waiting for the publication lock. Replacing an asset's project
while a new operation waits refuses that operation rather than writing under an
outdated scope. When reconciling through GET, use the original project scope.

The same GET above reads a version receipt. A confirmed result may name an older
version than the current asset. Missing receipts remain inconclusive until the
same key is reconciled; clients must not mint a fresh key merely after a timeout.
Staging failures retain existing cleanup. No cleanup runs after an ambiguous
COMMIT, where a confirmed version could already exist. A retry either finds its
receipt or uses the existing staging cleanup before the next attempt.

Legacy replacements without `publication` keep their existing behavior. Per-file
edits, restore, signed CI binding synchronization and MCP client propagation do
not gain publication identities through this change.
