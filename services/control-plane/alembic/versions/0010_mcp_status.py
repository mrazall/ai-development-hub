"""Store the last MCP registry check time."""

import sqlalchemy as sa
from alembic import op


revision = "0010_mcp_status"
down_revision = "0009_backups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mcp_servers",
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        schema="control",
    )


def downgrade() -> None:
    op.drop_column("mcp_servers", "checked_at", schema="control")
