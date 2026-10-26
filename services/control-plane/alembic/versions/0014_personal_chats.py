"""Add personal chat metadata to projects and sessions."""

from alembic import op
import sqlalchemy as sa

revision = "0014_personal_chats"
down_revision = "0013_engine_session_ref"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("is_personal", sa.Boolean(), nullable=False, server_default=sa.false()), schema="control")
    op.alter_column("projects", "is_personal", server_default=None, schema="control")
    op.add_column("sessions", sa.Column("chat_id", sa.String(36)), schema="control")
    op.add_column("sessions", sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()), schema="control")
    op.alter_column("sessions", "pinned", server_default=None, schema="control")
    op.add_column("sessions", sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()), schema="control")
    op.alter_column("sessions", "archived", server_default=None, schema="control")
    op.add_column("sessions", sa.Column("mcp_config", sa.JSON()), schema="control")
    op.create_index("ix_sessions_chat_id", "sessions", ["chat_id"], schema="control")


def downgrade() -> None:
    op.drop_index("ix_sessions_chat_id", table_name="sessions", schema="control")
    for name in ("mcp_config", "archived", "pinned", "chat_id"):
        op.drop_column("sessions", name, schema="control")
    op.drop_column("projects", "is_personal", schema="control")
