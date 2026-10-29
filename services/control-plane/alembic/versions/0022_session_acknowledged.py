"""A failed session the owner marked as fine."""
from alembic import op
import sqlalchemy as sa

revision = "0022_session_acknowledged"
down_revision = "0021_device_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("acknowledged_at", sa.DateTime(timezone=True)), schema="control")


def downgrade() -> None:
    op.drop_column("sessions", "acknowledged_at", schema="control")
