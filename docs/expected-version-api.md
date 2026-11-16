# Conditional asset version writes

Existing version-producing asset endpoints accept an optional positive integer
`expected_version`. Supply the version whose content the proposed write is based
on. The shared `commit_new_version` writer refreshes the asset with `FOR UPDATE`
and compares that version before clearing the staging prefix or writing files.

| Operation | Endpoint | Input location |
| --- | --- | --- |
| Edit Markdown | `PUT /api/assets/{id}/content` | JSON body |
| Add file | `POST /api/assets/{id}/files` | Multipart form |
| Create empty file | `POST /api/assets/{id}/files/empty` | JSON body |
| Delete file | `DELETE /api/assets/{id}/files` | Query parameter |
| Move file | `PATCH /api/assets/{id}/files/move` | JSON body |
| Replace version | `POST /api/assets/{id}/versions` | Multipart form |
| Restore version | `POST /api/assets/{id}/versions/{n}/restore` | Query parameter |

Two valid writes based on version N cannot both succeed with
`expected_version=N`: one creates N+1, and the other returns HTTP 409 with code
`version_conflict` and field `expected_version`. The rejected write leaves
storage, version rows and audit history untouched. Read the current document and
reconcile the intended change before retrying; do not blindly replace the
precondition with the newest number.

For example, an edit based on version 4 includes:

```json
{"path": "notes.md", "content": "Updated content", "expected_version": 4}
```

Omitting the field preserves the existing behavior: each valid write serializes
against the latest version and creates its successor. Existing response bodies,
archive reads, numbering and failure cleanup are unchanged. The signed CI sync
manifest keeps its existing contract. MCP tool propagation is tracked separately
in OpenProject #2353; this backend change does not make the optional field
mandatory for legacy callers.

A replacement carrying a [publication identity](publication-receipts-api.md)
requires `expected_version`. Its committed receipt is checked before CAS, so
retrying the same operation returns its original result rather than conflicting
with the version that operation already created. A different publication key
still needs a matching precondition.
