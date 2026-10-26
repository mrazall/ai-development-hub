"""Add attachment storage metadata and reversible project lifecycle state."""
import sqlalchemy as sa
from alembic import op

revision = "0011_attachments_lifecycle"
down_revision = "0010_mcp_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("archived_at", sa.DateTime(timezone=True)), schema="control")
    op.add_column("projects", sa.Column("deleted_at", sa.DateTime(timezone=True)), schema="control")
    op.create_table(
        "attachments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(63), sa.ForeignKey("control.projects.id"), nullable=False),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("control.sessions.id"), nullable=False),
        sa.Column("message_id", sa.String(255)),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("storage_path", sa.Text, nullable=False, unique=True),
        sa.Column("uploaded_by", sa.String(36), sa.ForeignKey("control.users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        schema="control",
    )
    for name, column in (("project_id", "project_id"), ("session_id", "session_id"), ("message_id", "message_id")):
        op.create_index(f"ix_control_attachments_{name}", "attachments", [column], schema="control")
    op.create_table(
        "project_lifecycle_errors",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(63), nullable=False),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("error", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="control",
    )
    op.create_index("ix_control_project_lifecycle_errors_project_id", "project_lifecycle_errors", ["project_id"], schema="control")


def downgrade() -> None:
    op.drop_table("project_lifecycle_errors", schema="control")
    op.drop_table("attachments", schema="control")
    op.drop_column("projects", "deleted_at", schema="control")
    op.drop_column("projects", "archived_at", schema="control")
