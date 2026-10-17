"""audit_log immutability trigger: English error message

Revision ID: 0029
Revises: 0028
Create Date: 2026-09-24

Same unconditional trigger as 0016, only the exception text changes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FUNCTION = """
CREATE OR REPLACE FUNCTION audit_log_immutable() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION '{message} (op: %, id: %)', TG_OP, OLD.id;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.execute(_FUNCTION.format(message="audit_log is append-only"))


def downgrade() -> None:
    op.execute(_FUNCTION.format(message="audit_log jest append-only"))
