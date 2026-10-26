"""How much a Claude Code session may do without asking: edits (default), ask (the owner approves in the panel),
auto (Claude's auto mode), all (bypassPermissions)."""
from alembic import op
import sqlalchemy as sa

revision = "0019_session_permission_mode"
down_revision = "0018_system_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("permission_mode", sa.String(16), nullable=False, server_default="edits"),
        schema="control",
    )


def downgrade() -> None:
    op.drop_column("sessions", "permission_mode", schema="control")
