"""Worker capability snapshots.

Moved out of 0003_orchestration by the orchestrator: 0003 is already applied in production and applied
migrations are never edited.
"""
import sqlalchemy as sa
from alembic import op

revision = "0007_worker_capabilities"
down_revision = "0006_mcp_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "worker_capabilities",
        sa.Column("worker_id", sa.String(128), sa.ForeignKey("control.workers.id"), primary_key=True),
        sa.Column("capabilities", sa.JSON, nullable=False),
        sa.Column("workspace_url", sa.Text),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        schema="control",
    )


def downgrade() -> None:
    op.drop_table("worker_capabilities", schema="control")
