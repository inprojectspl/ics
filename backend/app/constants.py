"""Central type vocabulary for ICS.

Single source of truth for enum-like string sets used across models, routes,
and the markdown plugin. Keeps the python/sqlalchemy/pydantic/regex worlds
referring to the same canonical values.
"""

from __future__ import annotations

from typing import Literal, get_args

# Users

AuthMethod = Literal["google_sso", "password", "invite"]

Role = Literal["user", "external", "admin"]
ROLES: tuple[Role, ...] = get_args(Role)
ROLE_REGEX = f"^({'|'.join(ROLES)})$"

# Limits

# Default per-user cap on a single html bundle upload. An admin raises it
# per user (`users.bundle_max_bytes`), like `storage_quota_bytes`.
# Enforced by `quota.assert_bundle_fits`.
DEFAULT_BUNDLE_MAX_BYTES = 5 * 1024 * 1024

# Assets

AssetKind = Literal[
    "md_single", "md_collection", "html_bundle", "pdf_doc", "office_doc", "gitlab_binding"
]

# Kinds stored as one uploaded document converted to Markdown at write time
# (`services.documents`): the extensions each accepts and the error code for
# any other file. Here rather than in the registry because core modules
# (`collections_io`) check them and must not import services.
DOCUMENT_FILES: dict[str, tuple[tuple[str, ...], str]] = {
    "pdf_doc": ((".pdf",), "pdf_file_required"),
    "office_doc": ((".docx", ".odt", ".doc"), "office_file_required"),
}

SecurityStatus = Literal["clean", "warn", "critical", "pending", "bypassed"]

# Shares

ShareMode = Literal["org_sso", "magic_email", "password", "public"]
SHARE_MODES: tuple[ShareMode, ...] = get_args(ShareMode)
SHARE_MODE_REGEX = f"^({'|'.join(SHARE_MODES)})$"

# Tokens

TokenPurpose = Literal["invite", "reset", "verify", "magic_link"]

# Email outbox

EmailPurpose = Literal["invite", "reset", "verify", "magic_link", "notification"]

# Callouts (Obsidian taxonomy)

CalloutType = Literal[
    "note",
    "info",
    "tip",
    "success",
    "question",
    "warning",
    "failure",
    "danger",
    "bug",
    "example",
    "quote",
]
CALLOUT_TYPES: frozenset[CalloutType] = frozenset(get_args(CalloutType))

# Audit actions
# Canonical action vocabulary. The frontend's AdminAudit filter dropdown
# should be generated from this list (exposed via /api/admin/audit/actions)
# to prevent drift.

AuditAction = Literal[
    # auth
    "login_ok",
    "login_failed",
    "login_rate_limited",
    "account_locked",
    "logout",
    "password_reset_requested",
    "password_reset_confirmed",
    "user_invited",
    "account_setup_completed",
    "sessions_revoked_on_lockout",
    # OAuth
    "oauth_consent_granted",
    "oauth_token_issued",
    "oauth_token_refreshed",
    # personal access tokens
    "pat_created",
    "pat_revoked",
    # assets
    "asset_uploaded",
    "asset_renamed",
    "asset_versioned",
    "asset_rolled_back",
    "asset_deleted",
    "asset_edited",
    "asset_pinned",
    "asset_unpinned",
    "asset_undeleted",
    "asset_tags_set",
    "asset_metadata_updated",
    "asset_reviewed",
    "asset_ocr_requested",
    "vault_file_added",
    "vault_file_deleted",
    "vault_file_moved",
    # security review
    "security_bypass_granted",
    "security_bypass_revoked",
    "cdn_allowlist_added",
    "cdn_allowlist_removed",
    # user management (admin actions)
    "user_role_changed",
    "user_quota_changed",
    "user_bundle_limit_changed",
    "user_autobypass_changed",
    "user_display_name_changed",
    "user_locked_by_admin",
    "user_unlocked_by_admin",
    "user_password_reset_by_admin",
    "user_reinvited",
    "user_deleted_by_admin",
    # shares
    "share_created",
    "share_revoked",
    "share_password_ok",
    "share_password_failed",
    "share_magic_claimed",
    "share_resolved",
    # bindings (GitLab)
    "binding_created",
    "binding_updated",
    "binding_rotated",
    "binding_deleted",
    "binding_synced",
    "binding_sync_failed",
    # comments
    "comment_posted",
    "comment_edited",
    "comment_deleted",
    # projects + per-user sharing
    "project_created",
    "project_updated",
    "project_deleted",
    "project_member_invited",
    "project_member_role_changed",
    "project_member_kicked",
    "project_invite_accepted",
    "project_left",
    "project_owner_transferred",
    "asset_project_changed",
    "asset_share_granted",
    "asset_share_revoked",
    # doc type vocabulary (admin)
    "doc_type_created",
    "doc_type_updated",
    "asset_project_share_added",
    "asset_project_share_removed",
    # relations (ADR-0016)
    "relation_added",
    "relation_updated",
    "relation_removed",
    "relations_rescanned",
    # external references (ADR-0018)
    "external_ref_added",
    "external_ref_removed",
    "external_refs_rekeyed",
    "project_external_ref_set",
    "project_key_documents_set",
]
AUDIT_ACTIONS: tuple[AuditAction, ...] = get_args(AuditAction)
