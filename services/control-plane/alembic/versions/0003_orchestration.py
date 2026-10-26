from alembic import op
import sqlalchemy as sa

revision = "0003_orchestration"
down_revision = "0001_control"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sessions", sa.Column("parent_session_id", sa.String(36)), schema="control")
    op.add_column("sessions", sa.Column("account_profile_id", sa.String(36)), schema="control")
    op.add_column("sessions", sa.Column("workspace_ref", sa.Text), schema="control")
    op.add_column("sessions", sa.Column("title", sa.String(500)), schema="control")
    op.create_index("ix_sessions_parent_session_id", "sessions", ["parent_session_id"], schema="control")
    op.create_table("notifications",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36)),
        sa.Column("category", sa.String(64), nullable=False), sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("title", sa.String(255), nullable=False), sa.Column("body", sa.Text, nullable=False),
        sa.Column("session_id", sa.String(36)), sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True)), schema="control")
    op.create_table("worker_requests",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("worker_id", sa.String(128), nullable=False),
        sa.Column("session_id", sa.String(36)), sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("path", sa.Text), sa.Column("status", sa.String(16), nullable=False),
        sa.Column("response", sa.JSON), sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)), schema="control")


def downgrade():
    op.drop_table("worker_requests", schema="control")
    op.drop_table("notifications", schema="control")
    op.drop_index("ix_sessions_parent_session_id", table_name="sessions", schema="control")
    for name in ("title", "workspace_ref", "account_profile_id", "parent_session_id"):
        op.drop_column("sessions", name, schema="control")
