"""Add orchestration role and configuration to sessions."""
from alembic import op
import sqlalchemy as sa

revision = "0016_orchestration"
down_revision = "0015_account_limits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("role", sa.String(16)), schema="control")
    op.add_column("sessions", sa.Column("orchestration", sa.JSON()), schema="control")


def downgrade() -> None:
    op.drop_column("sessions", "orchestration", schema="control")
    op.drop_column("sessions", "role", schema="control")
