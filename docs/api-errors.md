# API errors

Every error response from the ICS API has the same JSON shape:

```json
{"detail": "asset not found", "code": "asset_not_found"}
```

- `code` is stable and machine-readable. Clients branch on it and translate
  it for the user. It never changes once released; a new meaning gets a new
  code.
- `detail` is English text meant for developers and logs. It may change at
  any time and may contain values (paths, sizes). Do not parse it.
- Some errors carry a structured `detail` object instead of a string; the
  table says so.
- Some errors add a `field` key naming the input field at fault (for example
  `"field": "properties.budget"`); the table says so.
- Some errors add other top-level keys with the valid choices, so a client can
  retry without another request (for example `"anchors": ["endpoints", ...]`);
  the table says so. These lists are capped; a `<key>_total` key gives the full
  count when the list was cut.
- Error responses are sent with `Cache-Control: no-store`.

Backend: routes raise `app.errors.ApiError(status, code, detail)`, never a
bare `HTTPException`. Services and core helpers (`app/services`, quota, path
rules, bundle extraction, access checks) know nothing about HTTP: they raise a
domain error from `app/domain_errors.py` (`InvalidInputError(code, detail)`
and friends), and one exception handler maps its category to the status
(400, 403, 404, 409, 413) with the same body. A test
(`tests/test_api_errors.py`) fails when a code used in `backend/app` is
missing from this table, when `detail` text is not English, or when
`HTTPException` is constructed directly.

Frontend: `frontend/src/lib/errorMessages.ts` maps codes to UI messages through the `error.<code>` catalogue keys in `frontend/src/locales/*.json`.

## Generic codes

Used when an error has no specific code: Starlette's own responses (unknown
route, wrong method) and exceptions from third-party code.

| Code | Status | Meaning |
| --- | --- | --- |
| `bad_request` | 400 | Generic bad request. |
| `unauthorized` | 401 | Generic authentication failure. |
| `forbidden` | 403 | Generic permission failure. |
| `not_found` | 404 | Unknown route or generic missing resource. |
| `method_not_allowed` | 405 | HTTP method not supported by the route. |
| `conflict` | 409 | Generic conflict. |
| `gone` | 410 | Generic gone. |
| `payload_too_large` | 413 | Generic payload too large. |
| `unsupported_media_type` | 415 | Generic unsupported media type. |
| `validation_error` | 422 | Request failed schema validation. `detail` is FastAPI's list of validation errors. |
| `rate_limited` | 429 | Too many requests; see `Retry-After` when present. |
| `server_error` | 500 | Unexpected server error. |
| `service_unavailable` | 503 | Service unavailable. |
| `http_error` | other 4xx | Any other client error status. |

## Authentication and accounts

| Code | Status | Meaning |
| --- | --- | --- |
| `not_authenticated` | 401 | No session and no bearer token. |
| `invalid_token` | 401 | Bearer token is invalid, expired or revoked. The response has `WWW-Authenticate` so MCP clients refresh the token. |
| `session_invalid` | 401 | Session cookie has no server-side id; log in again. |
| `session_revoked` | 401, 403 | Session was revoked (logout, lockout). 403 on the OAuth consent page. |
| `session_mismatch` | 403 | OAuth consent was submitted from a different session. |
| `csrf_origin_rejected` | 403 | A state-changing request with cookies came from another origin (Origin or Sec-Fetch-Site). |
| `user_not_found` | 401, 404 | The account behind the session no longer exists (401), or an admin looked up an unknown user (404). |
| `account_locked` | 403 | The account is locked by an administrator. |
| `account_unverified` | 403 | The account's e-mail address is not verified yet. |
| `account_already_active` | 400 | Reinvite requested for an account that is already active. |
| `admin_required` | 403 | The endpoint needs the admin role. |
| `domain_not_allowed` | 403 | The e-mail domain is not on the allowlist (SSO login, org-only share link). |
| `invalid_credentials` | 401 | Wrong e-mail or password. Deliberately does not say which. |
| `weak_password` | 400 | Password does not meet the minimum length. |
| `password_account_required` | 400 | Password reset requested for an SSO account. |
| `self_register_disabled` | 403 | Self-registration is turned off. |
| `user_exists` | 409 | An account with this e-mail already exists. |
| `token_expired` | 400 | E-mail token (verify, invite, reset) has expired. |
| `token_invalid` | 400 | E-mail token is malformed or points at nothing. |
| `google_oidc_disabled` | 503 | Google login is not configured. |
| `google_rejected` | 400 | Google refused the authorization request. |
| `google_email_missing` | 400 | Google returned no e-mail address. |
| `google_email_unverified` | 403 | Google has not verified the e-mail address. |
| `rate_limited` | 429 | Too many login, reset, link or API attempts. |
| `pat_limit` | 413 | The user already has the maximum number of active personal access tokens (5). |
| `pat_expiry_invalid` | 400 | Token expiry is missing, in the past or more than 180 days away (`field`: `expires_at`). |
| `insufficient_scope` | 403 | The bearer token is read only (a personal access token with `ics:read`) and the method writes. |
| `pat_not_found` | 404 | Personal access token does not exist or belongs to another user. |

## OAuth authorization server

Codes follow the RFC 6749, RFC 7591 and RFC 8707 error names.

| Code | Status | Meaning |
| --- | --- | --- |
| `invalid_request` | 400 | Missing or malformed parameter (PKCE, refresh token, revoke body). |
| `invalid_grant` | 400 | Authorization code or refresh token is invalid, expired, reused or mismatched. |
| `invalid_scope` | 400 | Requested scope is not allowed. |
| `invalid_target` | 400 | `resource` is missing, not allowed or does not match. |
| `invalid_redirect_uri` | 400 | Redirect URI is missing or not registered. |
| `invalid_state_token` | 403 | Consent form state token is invalid. |
| `unauthorized_client` | 400 | Unknown client or client not allowed for this flow. |
| `unsupported_grant_type` | 400 | Grant type is not supported. |
| `unsupported_response_type` | 400 | Response type is not supported. |
| `oauth_not_configured` | 500 | `ICS_MCP_RESOURCE_URI` is not set on the server. |

## Assets and files

| Code | Status | Meaning |
| --- | --- | --- |
| `asset_not_found` | 404 | Asset does not exist, is deleted, or the caller may not see it. |
| `asset_critical` | 403 | Asset is flagged critical by the security scan; an admin must approve it before sharing. |
| `bundle_withheld` | 410 | HTML bundle or document (PDF, Office) is withheld pending admin review. |
| `file_not_found` | 404 | File does not exist in the asset or version. |
| `file_exists` | 409 | A file with this path already exists. |
| `source_missing` | 404 | Stored source files are missing. |
| `entry_missing` | 404 | The asset has no entry file. |
| `collection_only` | 400 | Operation works only on Markdown collections. |
| `markdown_only` | 400 | Option works only on Markdown files. |
| `html_only` | 400 | Option works only on `.html` files. |
| `not_html_bundle` | 400, 404 | Operation works only on HTML bundles. |
| `html_bundle_not_editable` | 400 | HTML bundles have no inline-editable source. |
| `kind_not_renderable` | 400 | Asset kind cannot be rendered by this endpoint. |
| `unsupported_kind` | 400 | Asset kind is not supported by this endpoint. |
| `md_file_required` | 400 | Only `.md` files are accepted here. |
| `md_files_required` | 400 | Upload contains no `.md` files. |
| `md_single_requires_one_file` | 400 | A single-document asset needs exactly one `.md` file. |
| `md_single_one_file` | 400 | A single-document asset has only its entry file. |
| `pdf_file_required` | 400 | Only one `.pdf` file is accepted here. |
| `invalid_pdf` | 400 | The file is not a readable PDF (no `%PDF` signature or unparseable). |
| `pdf_encrypted` | 400 | The PDF is protected with a password; its text cannot be read. |
| `pdf_extraction_failed` | 400 | Reading the PDF failed or took longer than the extraction timeout. |
| `pdf_too_large` | 413 | The PDF is over the per-file cap (`ICS_PDF_MAX_BYTES`). |
| `pdf_only` | 400 | Operation works only on PDF assets. |
| `pdf_not_editable` | 400 | PDFs have no inline-editable source; upload a new version. |
| `ocr_not_supported` | 400 | OCR applies to PDF documents only; text formats (Markdown, HTML, Office) have their text already. |
| `ocr_disabled` | 409 | OCR is turned off on this server (`ICS_OCR_ENABLED`). |
| `ocr_not_needed` | 409 | Every page of the current version has visible text; there is nothing for OCR to read (a scan with a text layer saved in the file, or a document with text from an earlier OCR run, still accepts a request). |
| `ocr_provider_unknown` | 400 | The OCR engine named in the request is not one this server offers (`ICS_OCR_PROVIDERS`). |
| `ocr_api_key_required` | 400 | The chosen OCR engine is a cloud one and the request carries no `api_key`. |
| `ocr_in_progress` | 409 | OCR of the current version is already queued or running; wait for it to finish before a retry. |
| `office_file_required` | 400 | Only one `.docx`, `.odt` or `.doc` file is accepted here. |
| `invalid_office_document` | 400 | The file is not a readable Word or ODF text document (detected from its content). |
| `office_encrypted` | 400 | The document is protected with a password; its text cannot be read. |
| `office_conversion_failed` | 400 | Converting the document failed or took longer than the conversion timeout. |
| `office_too_large` | 413 | The document is over the per-file cap (`ICS_OFFICE_MAX_BYTES`) or unpacks to more than `ICS_OFFICE_MAX_UNZIPPED_BYTES`. |
| `office_not_editable` | 400 | Office documents have no inline-editable source; upload a new version. |
| `no_accepted_files` | 400 | Upload contains no file with an allowed extension. |
| `no_files` | 400 | Upload or CI bundle contains no files. |
| `no_changes` | 400 | New content is identical to the current one. |
| `last_file` | 400 | Cannot delete the last file of a collection. |
| `path_required` | 400 | A file path is required. |
| `same_path` | 400 | Source and destination paths are identical. |
| `invalid_path` | 400 | Path is empty or escapes the asset (`..`). |
| `invalid_entry_path` | 400 | `entry_path` is not one of the uploaded files. |
| `duplicate_path` | 400 | The same path appears twice in an upload. |
| `invalid_file_content` | 400 | File content is missing, doubled or not valid base64. |
| `files_paths_mismatch` | 400 | `files` and `paths` have different lengths. |
| `html_entry_missing` | 400 | HTML bundle has no `.html` file. |
| `line_range_too_wide` | 400 | Requested line range exceeds the limit. |
| `file_too_large` | 400 | File has too many lines to return whole; use `lines=N-M`. |
| `text_slice_too_large` | 413 | Returned text slice exceeds the byte limit. |
| `binary_file` | 415 | File is binary. `detail` is an object: `code`, `mime`, `size_bytes`, `hint`. |
| `binary_too_large` | 413 | Binary file is too large for base64 transfer. |
| `upload_too_large` | 413 | Uploaded file or asset exceeds the size limit. |
| `request_too_large` | 413 | Request body exceeds the server limit. |
| `storage_quota_exceeded` | 413 | User's storage quota would be exceeded. |
| `bundle_too_large` | 413 | Bundle exceeds the size limit. |
| `bundle_too_many_files` | 413 | Bundle has too many files. |
| `bundle_invalid_archive` | 400 | Bundle is not a valid tar.gz archive. |
| `bundle_entry_rejected` | 400 | Archive contains a link, device or absolute path. |
| `invalid_cursor` | 400 | Pagination cursor is invalid. |

## Document metadata

| Code | Status | Meaning |
| --- | --- | --- |
| `doc_type_unknown` | 400 | Document type does not exist or is archived; existing assets keep an archived type, new assignments cannot pick it. |
| `doc_type_filter_unknown` | 400 | A `doc_type` filter of `/api/assets/index` or `/api/assets/search-mcp` names a type that does not exist (an archived type still filters). The body has `field: "doc_type"` and `allowed`, the active type keys. |
| `doc_type_exists` | 409 | A document type with this key already exists. |
| `doc_type_not_found` | 404 | Document type does not exist (admin edit). |
| `doc_type_schema_invalid` | 400 | `properties_schema` is not an object schema in the supported JSON Schema subset (see `backend/app/json_schema.py`). |
| `metadata_invalid` | 400 | A metadata field is invalid (summary too long, unknown maintainer, bad language tag, `properties` over 16 KB or not matching the document type schema). The body has `field` with the offending field or `properties` path. |

## Versions

| Code | Status | Meaning |
| --- | --- | --- |
| `version_not_found` | 404 | Version number is out of range. |
| `version_empty` | 404 | Version has no files. |
| `version_files_missing` | 404 | Stored files of the version are gone. |
| `version_is_current` | 400 | Restoring the version that is already current. |
| `invalid_version` | 400 | Version number is not valid for this operation. |
| `same_version` | 400 | Diff requested between a version and itself. |

## Sharing

| Code | Status | Meaning |
| --- | --- | --- |
| `share_not_found` | 404 | Share link or user share does not exist. |
| `share_revoked` | 410 | Link was revoked or its asset deleted. |
| `share_expired` | 410 | Link has expired. |
| `share_spent` | 410 | Link reached its open limit. |
| `share_access_denied` | 403 | Caller may not open this link. |
| `share_forbidden` | 403 | Caller may not share this asset. |
| `share_password_required` | 401 | Link is password protected; send the password. |
| `share_password_invalid` | 401 | Wrong link password (also returned when rate limited). |
| `share_login_required` | 401 | Link requires an organisation login. |
| `share_not_password` | 400 | Password sent to a link that has none. |
| `share_not_magic_email` | 400 | Magic-link claim on a link of another mode. |
| `share_with_owner` | 400 | Cannot share a file with its owner. |
| `share_exists` | 409 | The user already has access to this file. |
| `unsupported_share_mode` | 400 | Share mode is not supported. |
| `password_required` | 400 | Password mode needs a password. |
| `allowed_emails_required` | 400 | Magic-email mode needs a recipient list. |
| `email_not_allowed` | 403 | The e-mail address is not on the link's recipient list. |
| `link_expired` | 400 | Signed link (magic link, HTML grant) has expired. |
| `link_invalid` | 400 | Signed link is malformed or does not match the document. |
| `grant_required` | 401 | HTML bundle opened directly instead of through ICS. |

## Projects

| Code | Status | Meaning |
| --- | --- | --- |
| `project_not_found` | 404 | Project does not exist or the caller is not a member. |
| `project_role_required` | 403 | Caller's project role is too low. |
| `project_share_home` | 400 | The asset already belongs to this project, so it cannot be assigned to it. |
| `member_not_found` | 404 | Project member does not exist. |
| `already_member` | 409 | The user is already a project member. |
| `owner_required` | 403 | Only the project owner can do this. |
| `owner_role_locked` | 400 | The owner role changes only through ownership transfer. |
| `owner_cannot_leave` | 409 | The owner must transfer ownership before leaving. |
| `cannot_kick_owner` | 400 | The owner cannot be removed from the project. |
| `invalid_transfer_target` | 400 | Transfer target is not an accepted member. |
| `ownership_conflict` | 409 | A concurrent ownership transfer won; reload and retry. |
| `invitation_not_found` | 404 | Invitation does not exist. |
| `invitation_not_yours` | 403 | Invitation belongs to another account. |
| `invitation_already_accepted` | 409 | Invitation was already accepted. |
| `invitation_expired` | 410 | Invitation link has expired. |

## Relations

| Code | Status | Meaning |
| --- | --- | --- |
| `relation_not_found` | 404 | Relation does not exist, or the caller cannot see both ends (reading also needs graph access to one of them, writing editor on one of them). |
| `relation_self` | 400 | An asset cannot relate to itself. |
| `relation_exists` | 409 | The same relation already exists. |
| `relation_type_invalid` | 400 | Unknown relation type. |
| `relation_anchor_invalid` | 400 | A symmetric relation cannot point at a heading. |
| `relation_target_anchor_not_found` | 400 | `target_anchor` matches no heading (Markdown, converted documents) or element id (HTML) in the target's current version. The body has `anchors`: the valid anchors in document order, at most 30 (`anchors_total` when there are more). |
| `relation_target_path_not_found` | 400 | `target_path` is not a file of the target's current version. The body has `paths`: the files of that version, at most 30 (`paths_total` when there are more). |
| `relation_limit` | 413 | The asset already has the maximum number of relations (200). |
| `relation_cycle` | 409 | The relation would create a `supersedes` or `part_of` cycle among documents the caller can see. |

## External references

| Code | Status | Meaning |
| --- | --- | --- |
| `external_ref_invalid` | 400 | Unknown system, entity or role, or a malformed external id, scope, url or pinned version (`field` names it). |
| `external_ref_exists` | 409 | The document already has this link. |
| `external_ref_limit` | 413 | The document already has the maximum number of external links (100). |
| `external_ref_not_found` | 404 | Link does not exist, or the caller has no graph access to its document (reading) or cannot edit it (removing). |
| `project_external_taken` | 409 | The external project is already mapped to another ICS project (which one is not disclosed, ADR-0018). |

## Administration

| Code | Status | Meaning |
| --- | --- | --- |
| `invalid_role` | 400 | Unknown user role. |
| `last_admin` | 400 | Cannot remove or demote the last administrator. |
| `cannot_lock_self` | 400 | An admin cannot lock their own account. |
| `cannot_delete_self` | 400 | An admin cannot delete their own account. |
| `bypass_not_applicable` | 400 | Security bypass applies only to critical assets. |
| `bypass_already_granted` | 409 | Asset already has a security bypass. |
| `bypass_not_granted` | 400 | Asset has no security bypass to revoke. |
| `invalid_cdn_host` | 400 | CDN host is not a bare dotted domain. |
| `cdn_host_builtin` | 409 | Host is already a built-in trusted CDN. |
| `cdn_host_exists` | 409 | Host is already on the CDN allowlist. |
| `cdn_host_not_found` | 404 | CDN allowlist entry does not exist. |

## CI bindings

| Code | Status | Meaning |
| --- | --- | --- |
| `binding_not_found` | 404 | Binding does not exist or the caller does not own it. |
| `bad_signature` | 403 | Push signature does not verify. |
| `manifest_invalid` | 400 | Push manifest is not valid. |
| `manifest_mismatch` | 400 | Manifest names another binding. |
| `bundle_hash_mismatch` | 400 | Bundle SHA-256 differs from the manifest. |
| `commit_from_future` | 400 | Commit timestamp is too far in the future. |
| `replay_rejected` | 409 | Push is a replay or out of order. |
| `webhook_pair_incomplete` | 400 | `provider` and `webhook_url` must be set, cleared or patched together. |
| `invalid_webhook` | 400 | Unknown notification provider or URL not valid for it. |

## Notifications

| Code | Status | Meaning |
| --- | --- | --- |
| `invalid_cursor` | 400 | The `before` cursor is not a notification id. |
| `notification_not_found` | 404 | The notification is not in the caller's inbox. |
| `stream_browser_only` | 403 | The live stream needs a browser session, not a token. |
| `invalid_webhook_url` | 400 | Not a Google Chat incoming webhook URL. |
| `chat_not_configured` | 400 | No Google Chat webhook is set. |
| `chat_delivery_failed` | 502 | Google Chat did not accept the test message. |
| `push_not_configured` | 409 | Web Push is not set up on this server (no VAPID key). |
| `push_endpoint_not_allowed` | 400 | The push endpoint is not a known browser push service. |
| `push_subscription_not_found` | 404 | The device is not registered for the caller. |
| `invalid_unsubscribe_token` | 400 | The e-mail opt-out link is invalid or expired. |
