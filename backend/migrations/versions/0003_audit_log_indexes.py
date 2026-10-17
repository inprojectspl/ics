"""audit log filter indexes

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-12

Admin /audit endpoint filters by action (exact), actor (exact), target
(prefix LIKE 'kind:%'). Without these the table is full-scanned on every
filter, and audit_log only grows.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_audit_log_action", "audit_log", ["action"])
    op.create_index("ix_audit_log_actor", "audit_log", ["actor"])
    # text_pattern_ops supports prefix LIKE 'foo:%' on btree.
    op.create_index(
        "ix_audit_log_target",
        "audit_log",
        ["target"],
        postgresql_ops={"target": "text_pattern_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_audit_log_target", table_name="audit_log")
    op.drop_index("ix_audit_log_actor", table_name="audit_log")
    op.drop_index("ix_audit_log_action", table_name="audit_log")
