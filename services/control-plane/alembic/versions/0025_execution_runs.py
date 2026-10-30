"""Record individual execution runs."""
from alembic import op
import sqlalchemy as sa

revision = "0025_execution_runs"
down_revision = "0024_worker_models"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("execution_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("task_id", sa.String(36)), sa.Column("project_id", sa.String(63), nullable=False),
        sa.Column("run_index", sa.Integer(), nullable=False), sa.Column("external_run_id", sa.String(64)),
        sa.Column("engine", sa.String(32)), sa.Column("model", sa.String(128)),
        sa.Column("account_profile_id", sa.String(36)), sa.Column("role", sa.String(16)),
        sa.Column("orchestration_id", sa.String(36)), sa.Column("trigger", sa.String(24), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True)), sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)), sa.Column("status", sa.String(16), nullable=False),
        sa.Column("failure_reason", sa.Text()), sa.Column("attribution", sa.String(16), nullable=False),
        sa.Column("waiting_approval_s", sa.Float()), sa.Column("waiting_limit_s", sa.Float()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("session_id", "run_index"), schema="control")
    for col in ("session_id", "task_id", "project_id"):
        op.create_index(f"ix_control_execution_runs_{col}", "execution_runs", [col], schema="control")
    op.add_column("agent_events", sa.Column("run_id", sa.String(36)), schema="control")
    op.create_index("ix_control_agent_events_run_id", "agent_events", ["run_id"], schema="control")


def downgrade():
    op.drop_index("ix_control_agent_events_run_id", table_name="agent_events", schema="control")
    op.drop_column("agent_events", "run_id", schema="control")
    op.drop_table("execution_runs", schema="control")
