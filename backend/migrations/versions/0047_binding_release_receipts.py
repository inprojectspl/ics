"""Add a binding principal and generation to committed publication receipts.

Revision ID: 0047
Revises: 0046
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0047"
down_revision: str | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("gitlab_bindings", sa.Column("last_release_generation", sa.BigInteger()))
    op.add_column("publication_receipts", sa.Column("binding_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_publication_receipt_binding",
        "publication_receipts",
        "gitlab_bindings",
        ["binding_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.alter_column("publication_receipts", "principal_id", nullable=True)
    op.create_check_constraint(
        "ck_publication_receipt_principal",
        "publication_receipts",
        "(principal_id IS NOT NULL AND binding_id IS NULL) OR "
        "(principal_id IS NULL AND binding_id IS NOT NULL)",
    )
    op.create_unique_constraint(
        "uq_binding_publication_receipt", "publication_receipts", ["binding_id", "publication_id"]
    )


def downgrade() -> None:
    op.execute("DELETE FROM publication_receipts WHERE binding_id IS NOT NULL")
    op.drop_constraint("uq_binding_publication_receipt", "publication_receipts", type_="unique")
    op.drop_constraint("ck_publication_receipt_principal", "publication_receipts", type_="check")
    op.alter_column("publication_receipts", "principal_id", nullable=False)
    op.drop_constraint("fk_publication_receipt_binding", "publication_receipts", type_="foreignkey")
    op.drop_column("publication_receipts", "binding_id")
    op.drop_column("gitlab_bindings", "last_release_generation")
