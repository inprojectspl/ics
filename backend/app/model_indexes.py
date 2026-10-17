"""Migrated indexes mirrored into the ORM metadata, so `alembic check` sees no
drift and test `create_all` builds them too. Migrations stay the source of truth;
imported for its side effect by `app/models/__init__.py`.
"""

from sqlalchemy import Index, func, text

from app.models import (
    Asset,
    AssetExternalRef,
    AssetProjectShare,
    AssetRelation,
    AssetShare,
    AuditLog,
    AuthAttempt,
    DocumentOcr,
    DuplicateDismissal,
    OAuthAuthCode,
    OAuthClient,
    OAuthJTIBlacklist,
    OAuthRefreshToken,
    PersonalAccessToken,
    Project,
    ProjectExternalRef,
    ProjectKeyDocument,
    ProjectMember,
    ShareLink,
    User,
)

_LIVE_ASSET = text("deleted_at IS NULL")

INDEXES = (
    # users
    Index(
        "ix_users_last_login_at",
        User.last_login_at,
        postgresql_where=text("last_login_at IS NOT NULL"),
    ),
    Index(
        "ix_users_locked_until",
        User.locked_until,
        postgresql_where=text("locked_until IS NOT NULL"),
    ),
    # assets
    Index("ix_assets_owner_id", Asset.owner_id),
    Index("ix_assets_project", Asset.project_id),
    Index("ix_assets_content_updated_by", Asset.content_updated_by),
    Index("ix_assets_maintainer_id", Asset.maintainer_id),
    Index("ix_assets_reviewed_by", Asset.reviewed_by),
    Index(
        "ix_asset_project_doc_type",
        Asset.project_id,
        Asset.doc_type,
        postgresql_where=_LIVE_ASSET,
    ),
    Index(
        "ix_assets_review_due_at",
        Asset.review_due_at,
        postgresql_where=text("review_due_at IS NOT NULL"),
    ),
    Index(
        "ix_asset_content_updated_id",
        Asset.content_updated_at.desc(),
        Asset.id.desc(),
        postgresql_where=_LIVE_ASSET,
    ),
    Index("ix_asset_slug_active", Asset.slug, postgresql_where=_LIVE_ASSET),
    Index(
        "ix_asset_owner_updated",
        Asset.owner_id,
        Asset.updated_at.desc(),
        postgresql_where=_LIVE_ASSET,
    ),
    Index(
        "ix_asset_kind_updated",
        Asset.owner_id,
        Asset.kind,
        Asset.updated_at.desc(),
        postgresql_where=_LIVE_ASSET,
    ),
    Index(
        "ix_asset_project_created",
        Asset.project_id,
        Asset.created_at.desc(),
        postgresql_where=_LIVE_ASSET,
    ),
    Index(
        "ix_asset_project_updated",
        Asset.project_id,
        Asset.updated_at.desc(),
        postgresql_where=_LIVE_ASSET,
    ),
    Index(
        "ix_asset_updated_id",
        Asset.updated_at.desc(),
        Asset.id.desc(),
        postgresql_where=_LIVE_ASSET,
    ),
    Index(
        "ix_asset_outline_stale",
        Asset.outline_status,
        Asset.updated_at,
        postgresql_where=text("outline_status IN ('stale', 'building')"),
    ),
    Index(
        "ix_assets_security_pending",
        Asset.created_at,
        postgresql_where=text(
            "security_status = 'critical' AND security_bypass = false AND deleted_at IS NULL"
        ),
    ),
    Index("ix_asset_tags_gin", Asset.tags, postgresql_using="gin"),
    Index(
        "ix_assets_search_tsv",
        Asset.search_tsv,
        postgresql_using="gin",
        postgresql_where=_LIVE_ASSET,
    ),
    Index(
        "ix_assets_search_content_trgm",
        Asset.search_content,
        postgresql_using="gin",
        postgresql_ops={"search_content": "gin_trgm_ops"},
        postgresql_where=_LIVE_ASSET,
    ),
    Index(
        "ix_assets_title_lower_trgm",
        func.lower(Asset.title).label("title_lower"),
        postgresql_using="gin",
        postgresql_ops={"title_lower": "gin_trgm_ops"},
        postgresql_where=_LIVE_ASSET,
    ),
    # share_links
    Index(
        "ix_share_links_canonical",
        ShareLink.asset_id,
        postgresql_where=text("revoked_at IS NULL AND max_views IS NULL"),
    ),
    # auth_attempts
    Index(
        "ix_auth_attempts_email_failed_ts",
        AuthAttempt.email,
        AuthAttempt.timestamp,
        postgresql_where=text("succeeded = false"),
    ),
    # projects
    Index("ix_projects_slug", Project.slug, unique=True),
    # project_members
    Index("ix_project_members_project", ProjectMember.project_id),
    Index("ix_project_members_user", ProjectMember.user_id),
    Index(
        "ix_project_member_user_accepted",
        ProjectMember.user_id,
        postgresql_where=text("accepted_at IS NOT NULL"),
    ),
    Index(
        "uq_project_members_one_owner",
        ProjectMember.project_id,
        unique=True,
        postgresql_where=text("role = 'owner'"),
    ),
    # asset_shares
    Index("ix_asset_shares_asset", AssetShare.asset_id),
    Index("ix_asset_shares_user", AssetShare.user_id),
    Index("ix_asset_share_user_granted", AssetShare.user_id, AssetShare.granted_at.desc()),
    # asset_relations
    Index(
        "uq_asset_relation",
        AssetRelation.source_asset_id,
        AssetRelation.target_asset_id,
        AssetRelation.relation_type,
        func.coalesce(AssetRelation.source_path, "").label("source_path_key"),
        func.coalesce(AssetRelation.target_path, "").label("target_path_key"),
        func.coalesce(AssetRelation.target_anchor, "").label("target_anchor_key"),
        unique=True,
    ),
    Index(
        "ix_asset_relations_target",
        AssetRelation.target_asset_id,
        AssetRelation.relation_type,
    ),
    Index("ix_asset_relations_created_by", AssetRelation.created_by),
    # duplicate_dismissals: the primary key leads with asset_a_id.
    Index("ix_duplicate_dismissals_asset_b", DuplicateDismissal.asset_b_id),
    Index("ix_duplicate_dismissals_dismissed_by", DuplicateDismissal.dismissed_by),
    # asset_project_shares
    Index("ix_asset_project_shares_project", AssetProjectShare.project_id),
    Index("ix_asset_project_shares_created_by", AssetProjectShare.created_by),
    # asset_external_refs
    Index(
        "uq_asset_external_ref",
        AssetExternalRef.asset_id,
        AssetExternalRef.system,
        AssetExternalRef.entity,
        AssetExternalRef.external_id,
        AssetExternalRef.role,
        func.coalesce(AssetExternalRef.asset_path, "").label("asset_path_key"),
        unique=True,
    ),
    Index(
        "ix_asset_external_refs_lookup",
        AssetExternalRef.system,
        AssetExternalRef.entity,
        AssetExternalRef.external_id,
    ),
    Index("ix_asset_external_refs_created_by", AssetExternalRef.created_by),
    # project_external_refs
    Index(
        "uq_project_external",
        ProjectExternalRef.system,
        ProjectExternalRef.external_id,
        unique=True,
    ),
    Index("ix_project_external_refs_created_by", ProjectExternalRef.created_by),
    # project_key_documents
    Index("ix_project_key_documents_asset", ProjectKeyDocument.asset_id),
    # audit_log
    Index("ix_audit_log_action", AuditLog.action),
    Index("ix_audit_log_actor", AuditLog.actor),
    Index(
        "ix_audit_log_client_id",
        AuditLog.client_id,
        postgresql_where=text("client_id IS NOT NULL"),
    ),
    Index(
        "ix_audit_log_target",
        AuditLog.target,
        postgresql_ops={"target": "text_pattern_ops"},
    ),
    # oauth
    Index("ix_oauth_clients_client_id", OAuthClient.client_id, unique=True),
    Index(
        "ix_oauth_clients_active",
        OAuthClient.revoked_at,
        postgresql_where=text("revoked_at IS NULL"),
    ),
    Index("ix_oauth_auth_codes_client", OAuthAuthCode.client_id),
    Index("ix_oauth_auth_codes_user", OAuthAuthCode.user_id),
    Index("ix_oauth_auth_codes_expires", OAuthAuthCode.expires_at),
    Index(
        "ix_oauth_auth_codes_unused",
        OAuthAuthCode.code_hash,
        postgresql_where=text("used_at IS NULL"),
    ),
    Index("ix_oauth_refresh_token_hash", OAuthRefreshToken.token_hash, unique=True),
    Index("ix_oauth_refresh_client", OAuthRefreshToken.client_id),
    Index("ix_oauth_refresh_user", OAuthRefreshToken.user_id),
    Index(
        "ix_oauth_refresh_active",
        OAuthRefreshToken.user_id,
        OAuthRefreshToken.client_id,
        postgresql_where=text("revoked_at IS NULL"),
    ),
    Index(
        "ix_oauth_refresh_tokens_parent_id",
        OAuthRefreshToken.parent_id,
        postgresql_where=text("parent_id IS NOT NULL"),
    ),
    Index("ix_oauth_jti_expires", OAuthJTIBlacklist.expires_at),
    # personal_access_tokens
    Index("ix_personal_access_tokens_user", PersonalAccessToken.user_id),
    Index("ix_personal_access_tokens_prefix", PersonalAccessToken.token_prefix),
    Index(
        "ix_personal_access_tokens_active",
        PersonalAccessToken.user_id,
        postgresql_where=text("revoked_at IS NULL"),
    ),
    # document_ocr: the sweeper looks only at unfinished runs.
    Index(
        "ix_document_ocr_active",
        DocumentOcr.status,
        postgresql_where=text("status IN ('queued', 'running')"),
    ),
    Index(
        "ix_document_ocr_requested_by",
        DocumentOcr.requested_by,
        postgresql_where=text("requested_by IS NOT NULL"),
    ),
)
