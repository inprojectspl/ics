"""ORM models, split by theme. Every mapped class is re-exported here so
`from app.models import X` stays the single import path; all modules share
the one declarative `Base` from `app.db`."""

from app.models.assets import Asset, AssetPin, AssetVersion
from app.models.audit import AuditLog
from app.models.doc_types import DocType
from app.models.external_refs import AssetExternalRef, ProjectExternalRef, ProjectKeyDocument
from app.models.integrations import CdnAllowlist, GitLabBinding
from app.models.notifications import NotificationPreference, PushSubscription, Watch
from app.models.oauth import OAuthAuthCode, OAuthClient, OAuthJTIBlacklist, OAuthRefreshToken
from app.models.ocr import DocumentOcr
from app.models.projects import Project, ProjectMember
from app.models.relations import AssetRelation, DuplicateDismissal
from app.models.sharing import AssetProjectShare, AssetShare, ShareLink
from app.models.tokens import PersonalAccessToken
from app.models.users import AuthAttempt, EmailOutbox, User

__all__ = [
    "Asset",
    "AssetExternalRef",
    "AssetPin",
    "AssetProjectShare",
    "AssetRelation",
    "AssetShare",
    "AssetVersion",
    "AuditLog",
    "AuthAttempt",
    "CdnAllowlist",
    "DocType",
    "DocumentOcr",
    "DuplicateDismissal",
    "EmailOutbox",
    "GitLabBinding",
    "NotificationPreference",
    "OAuthAuthCode",
    "OAuthClient",
    "OAuthJTIBlacklist",
    "OAuthRefreshToken",
    "PersonalAccessToken",
    "Project",
    "ProjectExternalRef",
    "ProjectKeyDocument",
    "ProjectMember",
    "PushSubscription",
    "ShareLink",
    "User",
    "Watch",
]

# Registers the migrated indexes on these tables; see app/model_indexes.py.
# Last, because that module imports the classes above from this package.
from app import model_indexes  # noqa: F401
